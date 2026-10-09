---
name: epg-iptv
description: Diagnostica e mantém o EPG IPTV do Rafael (GitHub Actions + Pages). Use quando falarem de EPG, XMLTV, grade de canal errada ou ausente, HBO/Premiere/Discovery, fonte de EPG nova, workflow do Actions ou o link epg.xml.
---

# EPG-IPTV

1. Leia `AGENTS.md` na raiz do repositório (regras, arquitetura, limites). Respeite: **nunca** escrever credenciais, **não** commitar/pushar sem pedido, não logar em contas do dono.
2. Diagnóstico sem credenciais:
   - `python3 scripts/epgctl.py status` → última execução do Actions e arquivo publicado.
   - `python3 scripts/epgctl.py channel <texto>` → fonte, grade e agora/depois do canal (hora de Brasília).
   - `python3 scripts/epgctl.py summary` → totais e canais entregues por fonte.
   - Detalhes: `report.txt`, `channel_map.csv`, `channel_check.csv` no site publicado.
3. Para um problema de canal (nome sem casamento → `aliases` em `config.json`): ver a fonte usada; se existe um canal melhor em outra fonte, `mapping.json`; se o ID do provedor é compartilhado, `region_prefer` (config.json). Explique ao dono o que é limite do provedor (IDs repetidos, 4K sem ID, canais sem grade pública).
4. Nova fonte: **testar antes** (cobertura, data final, casamentos) e só então editar `config.json`.
5. Mudou o script? Rode localmente (credenciais por variável de ambiente, nunca em arquivo), confira o resumo de `docs/report.txt`, peça confirmação para commit/push, depois lembre que é preciso **rodar o workflow** e conferir com `epgctl.py status`.
6. Responda em português do Brasil, direto, com números (canais com EPG, fontes usadas).

## Pendências em aberto
Ver "Estado atual" no `AGENTS.md` (ESPN 2 × ESPN 3 e exemplos de variantes erradas do TVLOK). Canal sem casamento por nome → `aliases` em `config.json`; grade duplicada/genérica → seção "Receitas".
