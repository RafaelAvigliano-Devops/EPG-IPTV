#!/usr/bin/env python3
"""Gera um XMLTV próprio a partir da lista Xtream + fontes públicas.

Env: XTREAM_URL (ex: http://host), XTREAM_USER, XTREAM_PASS
mapping.json: {"epg_channel_id_do_provedor": "id_na_fonte_externa"}
"""
import gzip, io, json, os, re, sys, unicodedata, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cfg = json.load(open(os.path.join(ROOT, "config.json")))
mapping = json.load(open(os.path.join(ROOT, "mapping.json")))
BASE = os.environ["XTREAM_URL"].rstrip("/")
USER, PASS = os.environ["XTREAM_USER"], os.environ["XTREAM_PASS"]


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
    streams = json.loads(get(f"{BASE}/player_api.php?{q}&action=get_live_streams"))
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
        sys.exit("nenhuma fonte de EPG disponível")

    # índice por nome normalizado para fallback
    by_name = []
    for ch, _, _ in sources:
        idx = {}
        for cid, (names, _) in ch.items():
            for n in names + [cid]:
                idx.setdefault(norm(n), cid)
        by_name.append(idx)

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=cfg["min_hours_ahead"])
    win_min = now - timedelta(hours=cfg["hours_past"])
    win_max = now + timedelta(days=cfg["days_ahead"])
    out = ET.Element("tv", {"generator-info-name": "EPG-IPTV"})
    out_progs, report = [], {"ok": 0, "curto": [], "sem_epg": []}
    used, used_by_id, got, choice = {}, 0, set(), {}

    for eid, name in sorted(wanted.items()):
        best = None  # (last_stop, src_idx, src_id)
        major = max(group[eid], key=group[eid].get)  # nome dominante entre os streams deste ID
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
        for n in list(dict.fromkeys(stream_names[eid]))[:12]:
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
    chan_el = {}
    name_map = {}  # nome norm -> (cid_saida, fonte_i, cid_fonte)
    rows = []      # (stream_id, nome, categoria, tvg_id)
    siblings = {}  # nome norm -> eid (variante FHD/HD/SD/H265 do mesmo canal)
    for s in streams:
        if s.get("epg_channel_id"):
            siblings.setdefault(norm(s["name"]), s["epg_channel_id"])
    for s in no_id:
        key = norm(s["name"])
        if key in siblings and siblings[key] in emitted:
            rows.append((s["stream_id"], s["name"], siblings[key], "irmão"))
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
        if el is not None and s["name"] not in {d.text for d in el.findall("display-name")} and len(el.findall("display-name")) < 12:
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
        for n in src_names:
            f.write(f"  {n:<16} {used.get(n, 0):>5} usados\n")
        f.write("\n" + "=" * 50 + "\nDETALHES\n" + "=" * 50 + "\n")
        f.write(f"\nEPG curto/desatualizado ({len(report['curto'])}):\n" + "\n".join(report["curto"]))
        f.write(f"\n\nIDs do provedor sem EPG em nenhuma fonte ({len(report['sem_epg'])}):\n" + "\n".join(report["sem_epg"]))
        f.write(f"\n\nCanais sem epg_channel_id e sem EPG ({len(no_id_names)}):\n" + "\n".join(no_id_names))
    print(open(os.path.join(ROOT, "docs", "report.txt")).read()[:1100])


if __name__ == "__main__":
    main()
