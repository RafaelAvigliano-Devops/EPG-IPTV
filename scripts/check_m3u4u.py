#!/usr/bin/env python3
"""Verifica se o XML do m3u4u (link privado do dono) se atualiza sozinho.

Uso: M3U4U_EPG_URL='<link>' python3 scripts/check_m3u4u.py
O link NÃO fica gravado no repositório: o dono o informa na sessão.
Compara com monitoring/m3u4u_baseline.json.
"""
import gzip, hashlib, json, os, re, sys, urllib.request

url = os.environ.get("M3U4U_EPG_URL") or (sys.argv[1] if len(sys.argv) > 1 else "")
if not url:
    sys.exit("defina M3U4U_EPG_URL (link do m3u4u informado pelo dono)")
base = json.load(open(os.path.join(os.path.dirname(__file__), "..", "monitoring", "m3u4u_baseline.json")))
d = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=120).read()
if d[:2] == b"\x1f\x8b":
    d = gzip.decompress(d)
x = d.decode("utf8", "ignore")
cur = {"bytes": len(d), "sha256": hashlib.sha256(d).hexdigest(), "canais": x.count("<channel "),
       "start_min": min(re.findall(r'start="(\d{14})', x)), "stop_max": max(re.findall(r'stop="(\d{14})', x))}
for k in ("bytes", "canais", "start_min", "stop_max"):
    print(f"{k:10} baseline={base[k]}  agora={cur[k]}")
if cur["sha256"] == base["sha256"]:
    print("\nVEREDITO: IDÊNTICO -> o link NÃO se atualiza sozinho (retrato congelado). Pode remover o secret M3U4U_EPG_URL.")
elif cur["stop_max"] > base["stop_max"] or cur["start_min"] > base["start_min"]:
    print("\nVEREDITO: MUDOU e a grade avançou -> o link é VIVO. Manter o secret M3U4U_EPG_URL.")
else:
    print("\nVEREDITO: conteúdo mudou mas a grade não avançou -> inconclusivo; repetir mais tarde.")
