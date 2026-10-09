# EPG-IPTV

EPG (guia de programação XMLTV) próprio para lista IPTV Xtream, gerado e publicado automaticamente a cada 6 horas pelo GitHub Actions.

**Link do EPG:** `https://rafaelavigliano-devops.github.io/EPG-IPTV/epg.xml`

No app (ex.: TVLOK) coloque esse link em **EPG URL override**.

## Como funciona
O Actions lê a lista do provedor, baixa o EPG do provedor e de fontes públicas, casa os canais (por nome e por ID, priorizando a região) e publica um `epg.xml` enxuto no GitHub Pages. Detalhes técnicos, limites e decisões em [AGENTS.md](AGENTS.md).

## Configuração (uma vez)
1. Settings → Pages → Source: **GitHub Actions**.
2. Settings → Secrets and variables → Actions: `XTREAM_URL`, `XTREAM_USER`, `XTREAM_PASS` (e opcional `M3U4U_EPG_URL`).
3. Actions → *Atualizar EPG* → *Run workflow*.

## Avisos
O Actions abre **issues** (label `epg-alerta`) quando a conta está perto de vencer, o provedor não responde, a senha mudou, uma fonte de EPG cai ou para, ou um canal favorito fica sem grade. Se o provedor estiver fora, o EPG anterior continua publicado. Lista completa em [AGENTS.md](AGENTS.md).

## Diagnóstico
```bash
python3 scripts/epgctl.py status
python3 scripts/epgctl.py channel hbo
python3 scripts/epgctl.py summary
```
Relatórios publicados: `report.txt`, `channel_map.csv`, `channel_check.csv`.

## Arquivos
`scripts/build_epg.py` (gerador) · `config.json` (fontes e janela) · `mapping.json` (correções manuais) · `.github/workflows/epg.yml` · `.claude/skills/epg-iptv/` (skill para Claude Code).
