#!/usr/bin/env python3
"""Gera um XMLTV próprio a partir da lista Xtream + fontes públicas.

Env: XTREAM_URL (ex: http://host), XTREAM_USER, XTREAM_PASS
mapping.json: {"epg_channel_id_do_provedor": "id_na_fonte_externa"}
"""
import bisect, gzip, io, json, os, re, sys, time, unicodedata, urllib.request, urllib.parse
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
        if (p.findtext("title") or "").strip().lower() == "no data":  # vazio da iptv-epg.org: canal sem grade, não candidato
            continue
        progs.setdefault(cid, []).append(p)
        st = ts(p.get("stop", ""))
        if st and (cid not in last or st > last[cid]):
            last[cid] = st
    print(f"[{name}] {len(ch)} canais, {sum(map(len, progs.values()))} programas")
    return ch, progs, last


def is_filler(progs):
    """Grade genérica (poucos títulos distintos, ex.: 'Premiere 2' o dia todo): perde para grade com programação real."""
    return len({(p.findtext("title") or "").strip().lower() for p in progs}) <= 2


GENERIC = {"nodata", "filme", "progra", "sempro", "serie", "special", ""}  # títulos genéricos não provam nada


def tkey(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", re.split(r"[║|:\-–]", t)[0])[:6]


def _timeline(progs):
    d = {}
    for cid, lst in progs.items():
        if is_filler(lst):
            continue
        rows = sorted((ts(p.get("start")).timestamp(), ts(p.get("stop")).timestamp(), tkey(p.findtext("title"))) for p in lst)
        d[cid] = ([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
    return d


def _title_at(tl, t):
    i = bisect.bisect_right(tl[0], t) - 1
    return tl[2][i] if i >= 0 and t < tl[1][i] else None


def source_health(sources, by_name, now):
    """Compara cada fonte com as outras (mesmo canal por nome, mesmo instante): detecta fuso errado e fonte divergente.
    -> lista de dicts {i, n, r0, shift, rbest}; shift = horas a SOMAR aos horários da fonte para concordar com as demais."""
    tls = [_timeline(s[1]) for s in sources]
    instants = [now.timestamp() + h * 3600 for h in (1, 3, 5, 7, 11, 17)]
    shifts = range(-14, 15)
    out = []
    for i in range(len(sources)):
        sc = {sh: [0, 0] for sh in shifts}
        for key, cid in list(by_name[i].items())[:500]:
            a = tls[i].get(cid)
            if not a:
                continue
            for j in range(len(sources)):
                b = tls[j].get(by_name[j].get(key)) if j != i else None
                if not b:
                    continue
                for t in instants:
                    tb = _title_at(b, t)
                    if not tb or tb in GENERIC:
                        continue
                    for sh in shifts:
                        ta = _title_at(a, t - sh * 3600)
                        if ta and ta not in GENERIC:
                            sc[sh][1] += 1
                            sc[sh][0] += ta == tb
        ratio = {sh: (v[0] / v[1] if v[1] else 0) for sh, v in sc.items()}
        best = max(shifts, key=lambda sh: (ratio[sh], -abs(sh)))
        out.append({"i": i, "n": sc[0][1], "r0": ratio[0], "shift": best, "rbest": ratio[best]})
    return out


def name_keys(k):
    """'espn1' também procura 'espn' (o canal principal costuma ser publicado sem o número 1)."""
    return [k] + ([k[:-1]] if len(k) > 3 and k.endswith("1") and not k[-2].isdigit() else [])


def find_by_name(idx, key):
    return next((idx[k] for k in name_keys(key) if k in idx), None)


def _agree(a, b, instants):
    ok = n = 0
    for x in instants:
        ta, tb = _title_at(a, x), _title_at(b, x)
        if ta and tb and ta not in GENERIC and tb not in GENERIC:
            n += 1
            ok += ta == tb
    return ok, n


def consensus_pick(cands, cur, tls, instants, lasts=None):
    """cands {fonte_i: id_do_canal}. Se a escolhida diverge das demais (< 40%) e outra concorda com a maioria (>= 60%, apoiada
    por >= 2 fontes), devolve a fonte melhor. -> (fonte_i ou None, scores)"""
    scores = {}
    for i, cid in cands.items():
        a = tls[i].get(cid)
        if not a:
            continue
        vals = []
        for j, cj in cands.items():
            b = tls[j].get(cj) if j != i else None
            if b:
                ok, n = _agree(a, b, instants)
                if n >= 6:
                    vals.append(ok / n)
        if vals:
            scores[i] = (sum(vals) / len(vals), sum(v >= 0.5 for v in vals))
    if cur in scores and len(scores) >= 3:
        best = max(scores, key=lambda k: scores[k])
        if lasts:  # empate técnico (até 5 pontos) -> a fonte com a grade mais longa
            near = [k for k in scores if scores[k][0] >= scores[best][0] - 0.05 and scores[k][1] >= 2]
            best = max(near, key=lambda k: lasts.get(k) or 0) if near else best
        if best != cur and scores[cur][0] < 0.40 and scores[best][0] >= 0.60 and scores[best][1] >= 2:
            return best, scores
    return None, scores



def nome_confere(stream_names_, src_name):
    """O nome do canal na fonte combina com o nome do stream? (letras em comum e mesmo número; '1' ≙ sem número)"""
    b = vkey(src_name)
    db = {t for t in b if t.isdigit()}
    for n in stream_names_:
        a = vkey(n)
        da = {t for t in a if t.isdigit()}
        if (a - da) & (b - db) and (da == db or {"1"} in (da, db) and not (da and db)):
            return True
    return False


def fix_channel_shifts(sources, src_names, by_name, now):
    """Fuso errado só em alguns canais de uma fonte (ex.: parte do EPG_Share vem do epg.pw com -8 h): compara cada canal com o mesmo
    canal (por nome) das outras fontes e soma o deslocamento que fizer a concordância saltar (>= 60% e >= 2x a de 0 h)."""
    tls = [_timeline(x[1]) for x in sources]
    inst = [now.timestamp() + h * 3600 for h in (1, 2, 4, 6, 8, 10, 12, 15, 18, 21, 24, 30)]
    done, fixed = set(), []
    for i in range(len(sources)):
        for key, cid in list(by_name[i].items()):
            a = tls[i].get(cid)
            if not a or (i, cid) in done:
                continue
            refs = [tls[j].get(by_name[j].get(key)) for j in range(len(sources)) if j != i and by_name[j].get(key)]
            refs = [r for r in refs if r]
            if len(refs) < 2:
                continue
            def score(sh):
                ok = n = 0
                for b in refs:
                    for t in inst:
                        tb = _title_at(b, t)
                        ta = _title_at(a, t - sh * 3600) if tb and tb not in GENERIC else None
                        if ta and ta not in GENERIC:
                            n += 1
                            ok += ta == tb
                return ok, n
            ok0, n0 = score(0)
            if n0 < 8 or ok0 / n0 >= 0.5:
                continue
            sc = {sh: score(sh) for sh in range(-12, 13) if sh}
            best = max(sc, key=lambda sh: sc[sh][0] / max(sc[sh][1], 1))
            ob, nb = sc[best]
            if nb >= 8 and ob / nb >= 0.6 and ob / nb >= 2 * ok0 / n0:
                d = timedelta(hours=best)
                for p in sources[i][1][cid]:
                    for at in ("start", "stop"):
                        p.set(at, f"{ts(p.get(at)) + d:%Y%m%d%H%M%S} +0000")
                if cid in sources[i][2]:
                    sources[i][2][cid] += d
                done.add((i, cid))
                fixed.append(f"{src_names[i]}: {cid} {best:+d} h ({ok0 / n0:.0%} -> {ob / nb:.0%})")
    return fixed


def shift_source(source, hours):
    ch, progs, last = source
    d = timedelta(hours=hours)
    for lst in progs.values():
        for p in lst:
            for a in ("start", "stop"):
                p.set(a, f"{ts(p.get(a)) + d:%Y%m%d%H%M%S} +0000")
    for k in last:
        last[k] += d



def load_claro(name, city, days):
    """(o WAF da Claro exige q= como 1º parâmetro) Grade da Claro (API Solr pública do site) só para a janela necessária, convertida para o formato das outras fontes."""
    base = "https://programacao.claro.com.br/gatekeeper"
    q = lambda path, **kw: json.loads(get(f"{base}/{path}/select?" + urllib.parse.urlencode(kw, safe=":[]*-,") + "&wt=json"))["response"]["docs"]
    now = datetime.now(timezone.utc)
    # A Claro entrega horário LOCAL (Brasília, UTC-3) com sufixo "Z": tratar como -0300 (bug de 11/10: grade 3 h adiantada)
    loc = now - timedelta(hours=3)
    a, b = (loc - timedelta(hours=cfg["hours_past"] + 6)).strftime("%Y-%m-%dT%H:%M:00Z"), (loc + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:00Z")
    canais = q("canal", q=f"id_cidade:{city}", rows=1000, fl="id_canal nome cn_canal", fq="-cn_canal:0")
    ex = q("exibicao", q=f"id_cidade:{city}", rows=300000, fl="id_canal titulo genero dh_inicio dh_fim",
           fq=f"dh_inicio:[{a} TO {b}]")
    ch, progs, last = {}, {}, {}
    for c in canais:
        ch[f"claro.{c['id_canal']}"] = ([c["nome"].replace("³", "").strip()], None)
    fmt = lambda v: v.replace("-", "").replace(":", "").replace("T", "").replace("Z", "") + "00 -0300"
    for e in ex:
        cid = f"claro.{e['id_canal']}"
        if cid not in ch or not e.get("titulo"):
            continue
        p = ET.Element("programme", {"start": fmt(e["dh_inicio"]), "stop": fmt(e["dh_fim"]), "channel": cid})
        ET.SubElement(p, "title").text = e["titulo"]
        if e.get("genero"):
            ET.SubElement(p, "category").text = e["genero"]
        progs.setdefault(cid, []).append(p)
        st = ts(p.get("stop"))
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
    try:
        cat_name = {str(c["category_id"]): c["category_name"] for c in json.loads(get_retry(f"{BASE}/player_api.php?{q}&action=get_live_categories", tries=2))}
    except Exception:
        cat_name = {}
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
        if s.get("type") == "file":  # guia gerado por outro job do workflow (ex.: mi.tv via iptv-org/epg); opcional
            path = os.path.join(ROOT, s["path"])
            if not os.path.exists(path):
                print(f"fonte {s['name']} ignorada (arquivo {s['path']} ausente)")
                continue
            try:
                sources.append(load_source(s["name"], open(path, "rb").read()))
                src_names.append(s["name"])
            except Exception as e:
                print(f"fonte {s['name']} falhou:", e)
            continue
        if s.get("type") == "claro":
            try:
                sources.append(load_claro(s["name"], s["city"], s.get("days", 5)))
                src_names.append(s["name"])
            except Exception as e:
                print(f"fonte {s['name']} falhou:", e)
            continue
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
    esperadas = ["provedor"] + [x["name"] for x in cfg["sources"] if x.get("url") or x.get("type") == "claro" or (x.get("type") == "file" and os.path.exists(os.path.join(ROOT, x["path"]))) or os.environ.get(x.get("url_env", ""))]
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
        if curta >= 2 and nome not in cfg.get("fontes_curtas_ok", []):
            alert(f"fonte-parada-{nome}", f"Fonte de EPG '{nome}' parada",
                  f"A grade dessa fonte termina em {fim:%d/%m %H:%M} UTC" if fim else "Fonte sem programação.")

    # apelidos: nome do stream (norm) -> nome do canal na fonte (norm), p/ nomes que o casamento automático não liga
    alias = {norm(k): norm(v) for k, v in cfg.get("aliases", {}).items()}

    # índice por nome normalizado para fallback
    by_name = []
    names_only = {x["name"] for x in cfg["sources"] if x.get("names_only")}  # fontes cujo ID é só do site (ex.: mi.tv "br#espn-1")
    for si, (ch, progs, last) in enumerate(sources):
        idx = {}
        for cid, (names, _) in ch.items():
            if cid not in progs:  # canal sem programação não serve de candidato
                continue
            for n in names + ([] if src_names[si] in names_only else [cid]):
                k = norm(n)
                if k not in idx or (not is_filler(progs[cid]), last.get(cid, "")) > (not is_filler(progs[idx[k]]), last.get(idx[k], "")):
                    idx[k] = cid
        by_name.append(idx)

    now = datetime.now(timezone.utc)
    # --- saúde das fontes: corrige fuso errado e isola fonte que diverge das demais ---
    for n_, h_ in cfg.get("fuso_conhecido", {}).items():  # fuso já diagnosticado: corrige sem alarde
        if n_ in src_names:
            shift_source(sources[src_names.index(n_)], h_)
    health = source_health(sources, by_name, now)
    for h in health:
        i, nome = h["i"], src_names[h["i"]]
        h["acao"] = ""
        if h["n"] < 30:
            h["acao"] = "poucos dados para comparar"
        elif h["shift"] != 0 and h["rbest"] >= 0.40 and h["rbest"] >= 2 * h["r0"]:
            shift_source(sources[i], h["shift"])
            h["acao"] = f"horário corrigido automaticamente ({h['shift']:+d} h)"
            alert(f"fonte-fuso-{nome}", f"Fonte '{nome}' com horário deslocado ({h['shift']:+d} h), corrigida automaticamente",
                  f"Concordância de títulos com as outras fontes: {h['r0']:.0%} sem ajuste, {h['rbest']:.0%} com {h['shift']:+d} h. "
                  "O script somou o deslocamento aos horários desta fonte. Corrija a leitura de fuso no código da fonte.")
        elif h["r0"] < 0.15 and h["n"] >= 100:
            sources[i] = (sources[i][0], {}, {})
            by_name[i] = {}
            h["acao"] = "ISOLADA (diverge das demais)"
            alert(f"fonte-divergente-{nome}", f"Fonte '{nome}' divergente: isolada automaticamente",
                  f"Só {h['r0']:.0%} dos títulos coincidem com as outras fontes ({h['n']} comparações). Fonte ignorada nesta execução.")
        elif h["r0"] < 0.30:
            h["acao"] = "baixa concordância (só aviso)"
            alert(f"fonte-divergente-{nome}", f"Fonte '{nome}' com baixa concordância ({h['r0']:.0%})",
                  f"{h['n']} comparações com as outras fontes. Verifique fuso e casamento de canais.")
    canais_fuso = fix_channel_shifts(sources, src_names, by_name, now)  # fuso errado só em alguns canais
    tls = [_timeline(x[1]) for x in sources]  # depois dos ajustes de fuso
    instants = [now.timestamp() + h * 1800 for h in range(48)]  # próximas 24 h, de 30 em 30 min
    swaps = []  # canais em que o consenso das fontes trocou a escolha
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
        if eid in cfg.get("id_preferido", {}) and norm(cfg["id_preferido"][eid]) in group[eid]:
            major = norm(cfg["id_preferido"][eid])  # ID repetido pelo provedor: o dono escolheu quem fica com a grade
        major = alias.get(major, major)
        keys = name_keys(major)
        for stage in ("map", "name", "id"):
            for i, (ch, progs, last) in enumerate(sources):
                cand = {"map": mapping.get(eid), "name": find_by_name(by_name[i], major), "id": eid}[stage]
                if cand and cand in progs:
                    rank = (not is_filler(progs[cand]), last.get(cand, now))
                    if best is None or rank > best[0]:
                        best = (rank, i, cand)
            if best:
                break
        motivo = {"map": "mapping", "name": "nome", "id": "id"}[stage] if best else ""
        if best and stage != "map":  # revisão por consenso entre as fontes (mapping manual nunca é revisado)
            cands = {}
            for i, (ch, progs, last) in enumerate(sources):
                for cand in (find_by_name(by_name[i], major), eid):
                    if cand and cand in progs:
                        cands[i] = cand
                        break
            alt, sc = consensus_pick(cands, best[1], tls, instants, {i_: sources[i_][2].get(c_) for i_, c_ in cands.items()})
            if alt is not None:
                swaps.append(f"{eid} ({name}): {src_names[best[1]]} {sc[best[1]][0]:.0%} -> {src_names[alt]} {sc[alt][0]:.0%}")
                best = ((True, sources[alt][2].get(cands[alt], now)), alt, cands[alt])
                motivo = "consenso"
        if not best:
            report["sem_epg"].append(f"{eid} ({name})")
            continue
        _, i, cid = best
        stop_best = best[0][1]
        used[src_names[i]] = used.get(src_names[i], 0) + 1
        used_by_id += 1
        got.add(eid)
        choice[eid] = (src_names[i], cid, (sources[i][0].get(cid, ([""],))[0] or [""])[0], motivo)
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
        if stop_best >= horizon:
            report["ok"] += 1
        else:
            report["curto"].append(f"{eid} ({name}) até {stop_best:%d/%m %H:%M}")
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
                cid = find_by_name(by_name[i], key)
                if cid and cid in progs and (hit is None or (not is_filler(progs[cid]), last.get(cid, now)) > (hit[3], hit[2])):
                    hit = (i, cid, last.get(cid, now), not is_filler(progs[cid]))
            name_map[key] = hit
        hit = name_map[key]
        if not hit:
            rows.append((s["stream_id"], s["name"], "", ""))
            continue
        i, cid, stop, _ = hit
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


    # --- grades idênticas entre canais diferentes (sinal de ligação errada) ---
    seqs = {}
    for q_ in out_progs:
        a_, b_ = ts(q_.get("start")), ts(q_.get("stop"))
        if a_ and b_:
            seqs.setdefault(q_.get("channel"), []).append((a_.timestamp(), b_.timestamp(), tkey(q_.findtext("title"))))
    dtl = {}
    for c_, lst in seqs.items():
        lst.sort()
        dtl[c_] = ([x[0] for x in lst], [x[1] for x in lst], [x[2] for x in lst])
    nome_canal = {c.get("id"): (c.findtext("display-name") or c.get("id")) for c in out.findall("channel")}
    cat_of = {}  # id de saída -> categorias dos streams (para isentar redes de TV aberta e afiliadas)
    for x in streams:
        oid = x["epg_channel_id"] if x.get("epg_channel_id") else row_out.get(str(x["stream_id"]), "")
        if oid:
            cat_of.setdefault(oid, set()).add(cat_name.get(str(x.get("category_id")), "").upper())
    rede_tokens = [t.upper() for t in cfg.get("categorias_rede_ok", [])]
    is_rede = lambda oid: any(t in c for c in cat_of.get(oid, ()) for t in rede_tokens)
    ids_ = sorted(dtl)
    dups = []
    for x_ in range(len(ids_)):
        for y_ in range(x_ + 1, len(ids_)):
            ok_, n_ = _agree(dtl[ids_[x_]], dtl[ids_[y_]], instants)
            if n_ >= 10 and ok_ / n_ >= 0.85:
                if any(ids_[x_] in g_ and ids_[y_] in g_ for g_ in cfg.get("identicas_ok", [])):
                    continue  # todas as fontes concordam (placeholders/eventos); já conferido
                if is_rede(ids_[x_]) and is_rede(ids_[y_]):
                    continue  # TV aberta e afiliadas da mesma rede repetem a grade da cabeça de rede
                dups.append(f"{ids_[x_]} ({nome_canal[ids_[x_]]}) = {ids_[y_]} ({nome_canal[ids_[y_]]})  {ok_}/{n_}")
    if dups:
        alert("grades-identicas", f"Canais diferentes com a mesma grade ({len(dups)})",
              "Provável ligação errada (um canal recebendo a grade de outro):\n" + "\n".join(f"- {d}" for d in dups[:20]))

    path = os.path.join(ROOT, cfg["output"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ET.ElementTree(out).write(path, encoding="utf-8", xml_declaration=True)
    print(f"escrito {path}: {os.path.getsize(path)//1024} KB")
    lite = cfg.get("lite")
    if lite:
        fim_ = now + timedelta(days=lite["days_ahead"])
        root_ = ET.Element("tv", {"generator-info-name": "EPG-IPTV lite"})
        for c_ in out.findall("channel"):
            e_ = ET.SubElement(root_, "channel", {"id": c_.get("id")})
            for d_ in c_.findall("display-name")[: lite["max_names"]]:
                ET.SubElement(e_, "display-name").text = d_.text
        for q_ in out_progs:
            st_ = ts(q_.get("start"))
            if st_ and st_ <= fim_:
                e_ = ET.SubElement(root_, "programme", {k: q_.get(k) for k in ("start", "stop", "channel")})
                for tag_ in lite["keep"]:
                    for c_ in q_.findall(tag_)[:1]:
                        ET.SubElement(e_, tag_, c_.attrib).text = c_.text
        lp = os.path.join(ROOT, "docs", "epg-lite.xml")
        ET.ElementTree(root_).write(lp, encoding="utf-8", xml_declaration=True)
        print(f"escrito {lp}: {os.path.getsize(lp)//1024} KB")


    import csv as _csv
    with open(os.path.join(ROOT, "docs", "channel_check.csv"), "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["epg_id_provedor", "nome_no_provedor", "fonte", "id_na_fonte", "nome_na_fonte", "motivo", "nome_confere"])
        for eid, nm in sorted(wanted.items()):
            if eid in choice:
                w.writerow([eid, nm, *choice[eid], "sim" if nome_confere(stream_names[eid], choice[eid][2]) else "NAO"])
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
        f.write("\nSAUDE DAS FONTES (titulos iguais as outras fontes, mesmo canal e instante)\n")
        for h in health:
            f.write(f"  {src_names[h['i']]:<14} {h['r0']:>4.0%} de {h['n']:>5} comparacoes   {h['acao'] or 'ok'}   (melhor ajuste de fuso: {h['shift']:+d} h = {h['rbest']:.0%})\n")
        f.write("\nCANAIS ENTREGUES POR FONTE (a fonte com a grade mais longa vence)\n")
        for n, (_, _, lst) in zip(src_names, sources):
            fim = f"{max(lst.values()):%d/%m %H:%M}" if lst else "-"
            f.write(f"  {n:<16} {used.get(n, 0):>5} usados   grade da fonte ate {fim} UTC\n")
        f.write(f"\nFUSO CORRIGIDO POR CANAL: {len(canais_fuso)}\n")
        f.write("".join(f"  {x}\n" for x in canais_fuso[:40]))
        f.write(f"\nCONSENSO: {len(swaps)} canal(is) trocado(s) porque a fonte escolhida divergia das demais\n")
        f.write("".join(f"  {x}\n" for x in swaps))
        nomes_ruins = [f"{e} ({stream_names[e][0]}) -> {c[0]}: {c[2]} [{c[3]}]" for e, c in sorted(choice.items())
                       if not nome_confere(stream_names[e], c[2])]
        f.write(f"LIGACOES COM NOME DIFERENTE entre o canal e a grade usada ({len(nomes_ruins)}), conferir:\n")
        f.write("".join(f"  {x}\n" for x in nomes_ruins))
        f.write(f"GRADES IDENTICAS entre canais diferentes (fora das mesmas redes): {len(dups)}\n")
        f.write("".join(f"  {x}\n" for x in dups))
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
