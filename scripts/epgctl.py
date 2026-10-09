#!/usr/bin/env python3
"""Diagnóstico do EPG publicado. Não precisa de credenciais (só lê URLs públicas).

  python3 scripts/epgctl.py status            # últimas execuções do Actions + arquivo publicado
  python3 scripts/epgctl.py channel hbo       # canais cujo id/nome contém "hbo": fonte, grade, agora/próximo
  python3 scripts/epgctl.py summary           # resumo (report.txt publicado)
Variáveis opcionais: EPG_REPO (dono/repo), EPG_SITE (URL base do Pages).
"""
import csv, io, json, os, sys, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

REPO = os.environ.get("EPG_REPO", "RafaelAvigliano-Devops/EPG-IPTV")
SITE = os.environ.get("EPG_SITE", "https://rafaelavigliano-devops.github.io/EPG-IPTV").rstrip("/")
TZ = timezone(timedelta(hours=-3))  # Brasília


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "epgctl", "Accept-Encoding": "identity"})
    return urllib.request.urlopen(req, timeout=120).read()


def ts(s):
    d = datetime.strptime(s[:14], "%Y%m%d%H%M%S")
    off = s[15:].strip()
    if off and off[0] in "+-":
        delta = timedelta(hours=int(off[1:3]), minutes=int(off[3:5]))
        return (d - delta if off[0] == "+" else d + delta).replace(tzinfo=timezone.utc)
    return d.replace(tzinfo=timezone.utc)


def status():
    runs = json.loads(get(f"https://api.github.com/repos/{REPO}/actions/runs?per_page=3"))["workflow_runs"]
    for r in runs:
        print(f"run {r['id']}  {r['status']}/{r['conclusion']}  {r['created_at']}  commit {r['head_sha'][:7]}")
    if runs:
        jobs = json.loads(get(f"https://api.github.com/repos/{REPO}/actions/runs/{runs[0]['id']}/jobs"))["jobs"]
        for j in jobs:
            bad = [s["name"] for s in j["steps"] if s["conclusion"] not in ("success", "skipped", None)]
            print(f"  job {j['name']}: {j['status']}/{j['conclusion']}" + (f"  FALHOU EM: {bad}" if bad else ""))
    req = urllib.request.Request(f"{SITE}/epg.xml", method="HEAD", headers={"Accept-Encoding": "identity"})
    h = urllib.request.urlopen(req, timeout=60).headers
    print(f"publicado: {SITE}/epg.xml  {int(h['Content-Length'])/1e6:.1f} MB  Last-Modified {h['Last-Modified']}")


def channel(q):
    q = q.lower()
    root = ET.fromstring(get(f"{SITE}/epg.xml"))
    check = {r["epg_id_provedor"]: r for r in csv.DictReader(io.StringIO(get(f"{SITE}/channel_check.csv").decode()))}
    progs = {}
    for p in root.iter("programme"):
        progs.setdefault(p.get("channel"), []).append(p)
    now = datetime.now(timezone.utc)
    hit = 0
    for c in root.findall("channel"):
        cid = c.get("id")
        names = [d.text or "" for d in c.findall("display-name")]
        if q not in cid.lower() and not any(q in n.lower() for n in names):
            continue
        hit += 1
        ps = sorted(progs.get(cid, []), key=lambda p: p.get("start"))
        print(f"\n== {cid}   nomes: {', '.join(names[:6])}{'...' if len(names) > 6 else ''}")
        if cid in check:
            r = check[cid]
            print(f"   fonte: {r['fonte']}  canal na fonte: {r['id_na_fonte']} ({r['nome_na_fonte']})")
        if not ps:
            print("   SEM PROGRAMAS")
            continue
        print(f"   {len(ps)} programas, até {ts(ps[-1].get('stop')).astimezone(TZ):%d/%m %H:%M} (Brasília)")
        cur = [p for p in ps if ts(p.get("start")) <= now < ts(p.get("stop"))]
        nxt = [p for p in ps if ts(p.get("start")) > now][:2]
        for tag, lst in (("agora", cur), ("depois", nxt)):
            for p in lst:
                print(f"   {tag}: {ts(p.get('start')).astimezone(TZ):%H:%M} {p.findtext('title')}")
    if not hit:
        print("nenhum canal no XML publicado; veja channel_map.csv / report.txt (provavelmente sem EPG em nenhuma fonte)")


def main():
    a = sys.argv[1:]
    if a[:1] == ["status"]:
        status()
    elif a[:1] == ["channel"] and len(a) > 1:
        channel(" ".join(a[1:]))
    elif a[:1] == ["summary"]:
        print(get(f"{SITE}/report.txt").decode().split("DETALHES")[0])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
