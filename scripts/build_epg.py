#!/usr/bin/env python3
"""Gera um XMLTV próprio a partir da lista Xtream + fontes públicas.

Env: XTREAM_URL (ex: http://host), XTREAM_USER, XTREAM_PASS
mapping.json: {"epg_channel_id_do_provedor": "id_na_fonte_externa"}
"""
import gzip, io, json, os, re, sys, time, unicodedata, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

MAXN = 30  # máx. de display-name por canal
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cfg = json.load(open(os.path.join(ROOT, "config.json")))
mapping = json.load(open(os.path.join(ROOT, "mapping.json")))
prefer = {x.lower() for x in cfg.get("region_prefer", [])}
BASE = os.environ["XTREAM_URL"].rstrip("/")
USER, PASS = os.environ["XTREAM_USER"], os.environ["XTREAM_PASS"]


ALERTS = []                  # avisos desta execução -> alerts/alerts.json -> issues no GitHub
STATE_NEW = {"fontes": {}}   # estado publicado em docs/state.json (lido na próxima execução)


def alert(key, title, body, repeat=False):
    """key = identifica o aviso (uma issue aberta por key); repeat = comenta de novo a cada execução."""
    ALERTS.append({"key": key, "title": title, "body": body, "repeat": repeat})
    print("AVISO:", title)


def finish(publish):
    os.makedirs(os.path.join(ROOT, "alerts"), exist_ok=True)
    with open(os.path.join(ROOT, "alerts", "alerts.json"), "w") as f:
        # completo=False: execução interrompida; o workflow não pode dar issues antigas como resolvidas
        json.dump({"completo": bool(publish), "alertas": ALERTS}, f, ensure_ascii=False, indent=2)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"publish={'true' if publish else 'false'}\n")
    print(f"{len(ALERTS)} aviso(s); publicar={publish}")


def prev_state():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return {}
    owner, name = repo.split("/", 1)
    try:
        return json.loads(get(f"https://{owner.lower()}.github.io/{name}/state.json", 30))
    except Exception:
        return {}


def get_retry(url, tries=3, wait=int(os.environ.get("EPG_RETRY_WAIT", 30)), timeout=60):
    err = None
    for i in range(tries):
        try:
            return get(url, timeout)
        except Exception as e:
            err = e
            print(f"tentativa {i + 1}/{tries} falhou: {e}")
            if i < tries - 1:
                time.sleep(wait)
    raise err


def get(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req, timeout=timeout).read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("+", " plus ")
    s = re.sub(r"\b(fhd|hd|sd|uhd|4k|h265|h264|hevc|br|tv)\b|\[.*?\]|\(.*?\)", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


QUALITY = {"fhd", "hd", "sd", "uhd", "4k", "8k", "h265", "h264", "hevc", "alt", "fhdr", "hdr", "raw"}


def vkey(s):
    """Chave da variante: ignora qualidade (FHD/HD/SD/4K/H265/ALT), ordem e pontuação."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("+", " plus ")
    s = re.sub(r"\[.*?\]|\(.*?\)", " ", s)
    return frozenset(t for t in re.findall(r"[a-z0-9]+", s) if t not in QUALITY)


def ts(s):
    try:
        return datetime.strptime(s[:14], "%Y%m%d%H%M%S").replace(
            tzinfo=timezone(timedelta(seconds=0))) - _off(s)
    except Exception:
        return None


def _off(s):
    m = re.search(r"([+-])(\d{2})(\d{2})\s*$", s)
    if not m:
        return timedelta(0)
    d = timedelta(hours=int(m[2]), minutes=int(m[3]))
    return d if m[1] == "+" else -d


KEEP = ("title", "sub-title", "desc", "category", "episode-num")


def slim(p, out_id, start_min, start_max, desc_max):
    """Cópia enxuta do programa dentro da janela, ou None."""
    st, sp = ts(p.get("start", "")), ts(p.get("stop", ""))
    if not st or not sp or sp < start_min or st > start_max:
        return None
    q = ET.Element("programme", {"start": p.get("start"), "stop": p.get("stop"), "channel": out_id})
    for tag in KEEP:
        for c in p.findall(tag)[:1]:
            e = ET.SubElement(q, tag, c.attrib)
            e.text = (c.text or "")[:desc_max] if tag == "desc" else c.text
    return q if q.find("title") is not None else None


def load_source(name, raw):
    """-> (channels{id:(names,icon)}, progs{id:[elem]}, last_stop{id:dt})"""
    root = ET.fromstring(raw)
    ch, progs, last = {}, {}, {}
    for c in root.iter("channel"):
        names = [d.text or "" for d in c.findall("display-name")]
        icon = c.find("icon")
        ch[c.get("id")] = (names, icon.get("src") if icon is not None else None)
    for p in root.iter("programme"):
        cid = p.get("channel")
        progs.setdefault(cid, []).append(p)
        st = ts(p.get("stop", ""))
        if st and (cid not in last or st > last[cid]):
            last[cid] = st
    print(f"[{name}] {len(ch)} canais, {sum(map(len, progs.values()))} programas")
    return ch, progs, last


def main():
    os.makedirs(os.path.join(ROOT, os.path.dirname(cfg["output"])), exist_ok=True)
    q = urllib.parse.urlencode({"username": USER, "password": PASS})
    now = datetime.now(timezone.utc)
    try:
        info = json.loads(get_retry(f"{BASE}/player_api.php?{q}"))
        streams = json.loads(get_retry(f"{BASE}/player_api.php?{q}&action=get_live_streams"))
    except Exception as e:
        alert("provedor-fora", "Provedor Xtream sem resposta",
              f"O provedor não respondeu após 3 tentativas ({type(e).__name__}). "
              "O EPG anterior continua publicado. Se durar, o provedor pode ter trocado de endereço: "
              "atualize o secret `XTREAM_URL`.", repeat=True)
        return finish(False)
    ui = info.get("user_info") if isinstance(info, dict) else None
    if not isinstance(ui, dict) or str(ui.get("auth")) != "1" or not isinstance(streams, list) or not streams:
        alert("credenciais", "Provedor recusou a conta ou devolveu lista vazia",
              "A API respondeu, mas sem autenticação válida ou sem canais. Confira `XTREAM_USER` e `XTREAM_PASS` "
              "(o provedor pode ter trocado a senha). O EPG anterior continua publicado.", repeat=True)
        return finish(False)
    if ui.get("status") != "Active":
        alert("conta-status", f"Conta IPTV com status '{ui.get('status')}'", "O status da conta não é Active.")
    try:
        exp = datetime.fromtimestamp(int(ui["exp_date"]), timezone.utc)
        dias = (exp - now).days
        if dias <= 15:
            msg = "VENCEU" if exp < now else f"vence em {dias} dia(s)"
            alert("conta-expira", f"Conta IPTV {msg} ({exp:%d/%m/%Y})",
                  f"Data de vencimento informada pelo provedor: {exp:%d/%m/%Y %H:%M} UTC. "
                  "Renove com o provedor; se ele enviar um novo usuário/senha/host, atualize os secrets.")
    except (KeyError, TypeError, ValueError):
        pass
    prev = prev_state()
    if prev.get("streams") and len(streams) < 0.7 * prev["streams"]:
        alert("lista-mudou", "A lista do provedor encolheu muito",
              f"Antes {prev['streams']} canais, agora {len(streams)}. Pode ser troca de lista ou problema no provedor.")
    wanted = {}  # epg id -> nome
    group = {}   # epg id -> {nome normalizado: qtd}
    stream_names = {}  # id de saída -> nomes de streams (para o display-name)
    no_id = []   # streams sem epg_channel_id
    for s in streams:
        eid = s.get("epg_channel_id")
        if eid:
            wanted.setdefault(eid, s["name"])
            g = group.setdefault(eid, {})
            g[norm(s["name"])] = g.get(norm(s["name"]), 0) + 1
            stream_names.setdefault(eid, []).append(s["name"])
        else:
            no_id.append(s)
    print(f"{len(streams)} canais; {len(wanted)} ids de EPG; {len(no_id)} sem id")

    sources, src_names = [], []
    try:
        sources.append(load_source("provedor", get(f"{BASE}/xmltv.php?{q}")))
        src_names.append("provedor")
    except Exception as e:
        print("provedor xmltv falhou:", e)
    for s in cfg["sources"]:
        url = s.get("url") or os.environ.get(s.get("url_env", ""), "")
        if not url:
            print(f"fonte {s['name']} ignorada (sem URL)")
            continue
        try:
            sources.append(load_source(s["name"], get(url)))
            src_names.append(s["name"])
        except Exception as e:
            print(f"fonte {s['name']} falhou:", e)
    if not sources:
        alert("sem-fontes", "Nenhuma fonte de EPG disponível", "Todas as fontes falharam nesta execução; o EPG anterior continua publicado.", repeat=True)
        return finish(False)
    pf = prev.get("fontes", {})
    esperadas = ["provedor"] + [x["name"] for x in cfg["sources"] if x.get("url") or os.environ.get(x.get("url_env", ""))]
    for nome in esperadas:
        st = pf.get(nome, {})
        ok = nome in src_names
        fim = None
        if ok:
            lst = sources[src_names.index(nome)][2]
            fim = max(lst.values()) if lst else None
        falhas = 0 if ok else st.get("falhas", 0) + 1
        curta = (st.get("curta", 0) + 1) if (ok and (fim is None or fim < now + timedelta(hours=24))) else 0
        STATE_NEW["fontes"][nome] = {"falhas": falhas, "curta": curta}
        if falhas >= 2:
            alert(f"fonte-fora-{nome}", f"Fonte de EPG '{nome}' fora do ar",
                  f"Falhou em {falhas} execuções seguidas. O script continua com as outras fontes. "
                  "Verifique se o endereço mudou (config.json).")
        if curta >= 2:
            alert(f"fonte-parada-{nome}", f"Fonte de EPG '{nome}' parada",
                  f"A grade dessa fonte termina em {fim:%d/%m %H:%M} UTC" if fim else "Fonte sem programação.")

    # apelidos: nome do stream (norm) -> nome do canal na fonte (norm), p/ nomes que o casamento automático não liga
    alias = {norm(k): norm(v) for k, v in cfg.get("aliases", {}).items()}

    # índice por nome normalizado para fallback
    by_name = []
    for ch, progs, last in sources:
        idx = {}
        for cid, (names, _) in ch.items():
            if cid not in progs:  # canal sem programação não serve de candidato
                continue
            for n in names + [cid]:
                k = norm(n)
                if k not in idx or last.get(cid, "") > last.get(idx[k], ""):
                    idx[k] = cid
        by_name.append(idx)

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=cfg["min_hours_ahead"])
    win_min = now - timedelta(hours=cfg["hours_past"])
    win_max = now + timedelta(days=cfg["days_ahead"])
    out = ET.Element("tv", {"generator-info-name": "EPG-IPTV"})
    chan_el = {}
    out_progs, report = [], {"ok": 0, "curto": [], "sem_epg": []}
    used, used_by_id, got, choice = {}, 0, set(), {}

    for eid, name in sorted(wanted.items()):
        best = None  # (last_stop, src_idx, src_id)
        major = max(group[eid], key=group[eid].get)  # nome dominante entre os streams deste ID
        if len(group[eid]) > 1 and prefer:  # ID repetido: prioriza o canal da sua região
            for nm in stream_names[eid]:
                if prefer.intersection(re.findall(r"[a-z0-9]+", nm.lower())):
                    major = norm(nm)
                    break
        major = alias.get(major, major)
        for stage in ("map", "name", "id"):
            for i, (ch, progs, last) in enumerate(sources):
                cand = {"map": mapping.get(eid), "name": by_name[i].get(major), "id": eid}[stage]
                if cand and cand in progs and (best is None or last.get(cand, now) > best[0]):
                    best = (last.get(cand, now), i, cand)
            if best:
                break
        if not best:
            report["sem_epg"].append(f"{eid} ({name})")
            continue
        _, i, cid = best
        used[src_names[i]] = used.get(src_names[i], 0) + 1
        used_by_id += 1
        got.add(eid)
        choice[eid] = (src_names[i], cid, (sources[i][0].get(cid, ([""],))[0] or [""])[0])
        ch, progs, _ = sources[i]
        names, icon = ch.get(cid, ([name], None))
        c = ET.SubElement(out, "channel", {"id": eid})
        chan_el[eid] = c
        for n in list(dict.fromkeys(stream_names[eid]))[:MAXN]:
            ET.SubElement(c, "display-name").text = n
        if icon:
            ET.SubElement(c, "icon", {"src": icon})
        for p in progs[cid]:
            q = slim(p, eid, win_min, win_max, cfg["desc_max"])
            if q is not None:
                out_progs.append(q)
        if best[0] >= horizon:
            report["ok"] += 1
        else:
            report["curto"].append(f"{eid} ({name}) até {best[0]:%d/%m %H:%M}")
    # --- canais sem epg_channel_id: casa por nome ---------------------
    emitted = {c.get("id") for c in out.findall("channel")}
    name_map = {}  # nome norm -> (cid_saida, fonte_i, cid_fonte)
    rows = []      # (stream_id, nome, categoria, tvg_id)
    siblings = {}  # nome norm -> eid (variante FHD/HD/SD/H265 do mesmo canal)
    for s in streams:
        if s.get("epg_channel_id"):
            siblings.setdefault(vkey(s["name"]), s["epg_channel_id"])
    for s in no_id:
        key = norm(s["name"])
        key = alias.get(key, key)
        vk = vkey(s["name"])
        if vk in siblings and siblings[vk] in emitted:
            el = chan_el.get(siblings[vk])
            if el is not None and s["name"] not in {d.text for d in el.findall("display-name")}:
                ET.SubElement(el, "display-name").text = s["name"]
            rows.append((s["stream_id"], s["name"], siblings[vk], "irmão"))
            continue
        if key not in name_map:
            hit = None
            for i, (ch, progs, last) in enumerate(sources):
                cid = by_name[i].get(key)
                if cid and cid in progs and (hit is None or last.get(cid, now) > hit[2]):
                    hit = (i, cid, last.get(cid, now))
            name_map[key] = hit
        hit = name_map[key]
        if not hit:
            rows.append((s["stream_id"], s["name"], "", ""))
            continue
        i, cid, stop = hit
        used[src_names[i]] = used.get(src_names[i], 0) + 1
        out_id = cid
        if out_id not in emitted:
            emitted.add(out_id)
            ch, progs, _ = sources[i]
            names, icon = ch.get(cid, ([s["name"]], None))
            c = ET.SubElement(out, "channel", {"id": out_id})
            chan_el[out_id] = c
            ET.SubElement(c, "display-name").text = names[0] if names else s["name"]
            if icon:
                ET.SubElement(c, "icon", {"src": icon})
            for p in progs[cid]:
                q = slim(p, out_id, win_min, win_max, cfg["desc_max"])
                if q is not None:
                    out_progs.append(q)
        el = chan_el.get(out_id)
        if el is not None and s["name"] not in {d.text for d in el.findall("display-name")} and len(el.findall("display-name")) < MAXN:
            ET.SubElement(el, "display-name").text = s["name"]
        rows.append((s["stream_id"], s["name"], out_id, f"{stop:%d/%m %H:%M}"))
    matched = sum(1 for r in rows if r[2])
    import csv
    with open(os.path.join(ROOT, "docs", "channel_map.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stream_id", "nome", "tvg_id_sugerido", "grade_ate"])
        w.writerows(rows)
    no_id_names = [r[1] for r in rows if not r[2]]
    print(f"sem id: {matched} casados por nome, {len(no_id_names)} sem EPG")

    for p in out_progs:
        out.append(p)

    out_last = {}
    for q_ in out_progs:
        st_, c_ = ts(q_.get("stop")), q_.get("channel")
        if st_ and (c_ not in out_last or st_ > out_last[c_]):
            out_last[c_] = st_
    row_out = {str(r[0]): r[2] for r in rows}
    probs = []
    for fav in cfg.get("favoritos", []):
        ss = [x for x in streams if fav.lower() in x["name"].lower()]
        if not ss:
            probs.append(f"- **{fav}**: nenhum canal com esse nome na lista do provedor")
            continue
        ids = [(x["epg_channel_id"] if x["epg_channel_id"] in got else "") if x.get("epg_channel_id")
               else row_out.get(str(x["stream_id"]), "") for x in ss]
        com = [i for i in ids if i]
        if len(com) < len(ss) / 2:
            probs.append(f"- **{fav}**: só {len(com)} de {len(ss)} streams têm EPG")
        curtos = sorted({i for i in com if out_last.get(i, now) < now + timedelta(hours=12)})
        if curtos:
            probs.append(f"- **{fav}**: grade acaba em menos de 12 h em {', '.join(curtos)}")
    if probs:
        alert("favoritos", f"Canais favoritos com problema ({len(probs)})", "\n".join(probs))

    path = os.path.join(ROOT, cfg["output"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ET.ElementTree(out).write(path, encoding="utf-8", xml_declaration=True)
    print(f"escrito {path}: {os.path.getsize(path)//1024} KB")

    import csv as _csv
    with open(os.path.join(ROOT, "docs", "channel_check.csv"), "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["epg_id_provedor", "nome_no_provedor", "fonte", "id_na_fonte", "nome_na_fonte"])
        for eid, nm in sorted(wanted.items()):
            if eid in choice:
                w.writerow([eid, nm, *choice[eid]])
    siblings_n = sum(1 for r in rows if r[3] == "irmão")
    by_name_n = matched - siblings_n
    streams_by_id = sum(1 for x in streams if x.get("epg_channel_id") in got)
    with_epg = streams_by_id + matched
    with open(os.path.join(ROOT, "docs", "report.txt"), "w") as f:
        f.write(f"RESUMO - gerado em {now:%Y-%m-%d %H:%M} UTC\n")
        f.write("=" * 50 + "\n")
        f.write(f"Canais na lista do provedor ........ {len(streams)}\n")
        f.write(f"  Com EPG ........................... {with_epg}\n")
        f.write(f"    por ID do provedor .............. {streams_by_id} ({used_by_id} IDs unicos)\n")
        f.write(f"    por nome (sem ID no provedor) ... {by_name_n}\n")
        f.write(f"    por variante irma (FHD/HD/SD) ... {siblings_n}\n")
        f.write(f"  Sem EPG em nenhuma fonte .......... {len(streams) - with_epg}\n")
        f.write(f"Grade com >= {cfg['min_hours_ahead']}h a frente ......... {report['ok']} (IDs do provedor)\n")
        f.write(f"Grade curta/desatualizada ........... {len(report['curto'])}\n")
        f.write("\nCANAIS ENTREGUES POR FONTE (a fonte com a grade mais longa vence)\n")
        for n, (_, _, lst) in zip(src_names, sources):
            fim = f"{max(lst.values()):%d/%m %H:%M}" if lst else "-"
            f.write(f"  {n:<16} {used.get(n, 0):>5} usados   grade da fonte ate {fim} UTC\n")
        f.write("\n" + "=" * 50 + "\nDETALHES\n" + "=" * 50 + "\n")
        f.write(f"\nEPG curto/desatualizado ({len(report['curto'])}):\n" + "\n".join(report["curto"]))
        f.write(f"\n\nIDs do provedor sem EPG em nenhuma fonte ({len(report['sem_epg'])}):\n" + "\n".join(report["sem_epg"]))
        f.write(f"\n\nCanais sem epg_channel_id e sem EPG ({len(no_id_names)}):\n" + "\n".join(no_id_names))
    STATE_NEW.update(streams=len(streams), gerado=f"{now:%Y-%m-%dT%H:%M}Z")
    with open(os.path.join(ROOT, "docs", "state.json"), "w") as f:
        json.dump(STATE_NEW, f, indent=2)
    print(open(os.path.join(ROOT, "docs", "report.txt")).read()[:1100])
    finish(True)


if __name__ == "__main__":
    main()
