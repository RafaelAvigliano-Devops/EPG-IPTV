# HISTORICO — decisões, armadilhas e operação (EPG-IPTV)

Complementa o [AGENTS.md](AGENTS.md) (regras, arquitetura, estado atual). Aqui fica o **porquê** e o **como aprendemos**. Ordem cronológica; o mais recente embaixo.

## 2026-10-09 — dia de ampliação de fontes e qualidade
Ponto de partida: 1.140 de 2.034 canais com EPG; fontes públicas + provedor + m3u4u (link privado).

### Commits do dia (do mais antigo ao mais novo)
| Commit | O que mudou |
|---|---|
| `eb88371` | Avisos por issue, backlog (estado de partida) |
| `ad0e890` | **`aliases`** em `config.json` (19 apelidos): Record SP, BBC, NSports, USA Network, Sony, Premiere 1, Sportynet 01/04, NFL, Record GO/BH/Florianópolis, Globo RPC Maringá, Liberal Belém, Gazeta ES. m3u4u deixou de ser necessário (dono apagou o secret) |
| `736ed76` | **Fonte Claro** (`type: claro`, cidade 190 Canoas-RS), SBT/Band RS pela Claro no `mapping.json`, apelido Globo Passo Fundo |
| `b5ef8c2` | **Grade genérica perde para grade real** (`is_filler`) + descarte de programas "No Data" |
| `8c7a4c5` | Documentação consolidada do dia |
| `8dc462f` | `espn.2.br` fixa em `ESPN2.br` (regressão causada pela Claro) |
| `b0360e3` | Teste real dos scrapers iptv-org documentado |
| `e0e61eb` | **mi.tv** como fonte de reserva (job isolado `mitv`, `type: file`, `names_only`) |

Resultado medido no Actions (run `37985262026`): 1.161 com EPG / 873 sem. A cobertura quase não mudou; o ganho foi **qualidade** (Premiere 2/3/4, Canal do Boi/Rural, Rede Gospel, RIT, TV Aparecida, Band/SBT RS passaram a ter grade real; XML 6,5 → 5,7 MB; 0 "No Data").

### Armadilhas aprendidas (leia antes de mexer)
1. **A fonte com a grade mais longa nem sempre é a melhor.** `iptv-epg-br` preenche canais sem dado com programas "No Data" (72 por canal) ou com o próprio nome do canal ("Premiere 2" o dia todo) e ganhava de grades reais mais curtas → vários canais "idênticos". Solução: `is_filler()` e descarte de "No Data" em `load_source`.
2. **Claro rotula "ESPN 2 HD" o conteúdo que outras 4 fontes chamam de ESPN 3** → ESPN 2 e 3 saíram idênticas. Em canais numerados, conferir com ao menos uma segunda fonte (auditoria em 100 canais: só a ESPN 2 divergia). ESPN 2 = ESPN repetida com ~3 h de atraso (iptv-epg-br, epgshare-br, open-epg-3 e mi.tv concordam). **Dono ainda deve confirmar na TV.**
3. **API da Claro (Solr, sem login):** `https://programacao.claro.com.br/gatekeeper/{canal|exibicao|cidade}/select`. O WAF (CloudFront) devolve **403 se `wt=json` vier antes de `q=`** ou se `:` for codificado (`%3A`); a data do Solr precisa de segundos (`...T12:00:00Z`) senão 500. Cidade: `cidade/select?q=nome_novo:canoas&fq=uf:RS` → `id_cidade=190`. Só título/gênero/elenco, sem sinopse. Não é API documentada: pode mudar.
4. **IDs do mi.tv (`br#espn-1`) têm sufixo de desambiguação do site**, não é número do canal (`espn-1` = ESPN Extra, `espn-2` = ESPN). Indexar por ID fazia "ESPN 1" casar com a ESPN Extra → `names_only`.
5. **Caracteres como `³` nos nomes da Claro** ("HBO HD ³"): `norm()` já os descarta (não alfanumérico).
6. Ao inspecionar XML com `iterparse` + `el.clear()`, os filhos são limpos antes do pai (nomes/títulos vêm `None`); use `ET.fromstring` ou leia no evento do filho.
7. Apelidos devem ser **validados contra dados reais** (alvo existe, tem programação real, data final). Dois apelidos (Gazeta Alagoas) apontavam para "No Data" e foram removidos.
8. Dois sites do iptv-org (`guiadetv.com`, `meuguia.tv`) estão **quebrados** (0 programas); `mi.tv`, `vivoplay.com.br`, `clarotvmais.com.br` funcionam.

9. **(11/10) Claro estava 3 h adiantada em todos os canais.** A API devolve `dh_inicio`/`dh_fim` em **horário local de Brasília com sufixo `Z`**; o código os lia como UTC. Como a Claro vencia em ~160 canais (grade mais longa), o TVLOK mostrava programa errado em quase tudo. A "auditoria" anterior comparou só títulos, não **horários**. Detecção: concordância de títulos com o XMLTV do provedor no mesmo instante: Claro 9% → com +3 h 68% → depois da correção (`-0300`) 71%. Correção: `load_claro` marca `-0300` e usa a hora local na janela da consulta.
10. **Proteção automática (`source_health`)**: a cada execução cada fonte é comparada com as outras (mesmo canal por nome, mesmo instante, ignorando títulos genéricos). Se somar N horas aos horários da fonte faz a concordância saltar (≥ 40% e ≥ 2× a de 0 h), o script **corrige o fuso sozinho** e abre a issue `fonte-fuso-<nome>`; fonte com < 15% de concordância (≥ 100 comparações) é **isolada** (`fonte-divergente-<nome>`). Testado reintroduzindo o bug da Claro: detectou +3 h. Ao ligar, achou `epgpw-br` com −8 h (84% corrigido) e isolou `epgshare-pt` (13%, canais PT homônimos). Mantenha: **toda fonte nova deve passar pela comparação de horário, não só de títulos**.

11. **(11/10) ESPN 1 = ESPN 2 e "Discovery TLC = Discovery Channel" vinham do provedor.** O XMLTV do provedor entrega para `espn.br` ("ESPN 1") a mesma grade da ESPN 2 e para `discovery.br` ("DISCOVERY TLC") a grade do Discovery Channel. O nome "ESPN 1" nunca casava com "ESPN" nas fontes (o canal principal é publicado sem o número), então só sobrava o ID do provedor. Correções: `name_keys()` (`espn1` também procura `espn`), alias `DISCOVERY TLC → TLC`. O guia anterior dizia que "ESPN 2 = ESPN repetida com 3 h de atraso": **era leitura errada** (comparou com a cópia do provedor); as fontes mostram programação diferente nos dois.
12. **Revisão por consenso (`consensus_pick`)**: para cada canal (exceto `mapping.json`, que é manual), compara a fonte escolhida com as candidatas das outras fontes (próximas 24 h, de 30 em 30 min, títulos genéricos ignorados). Se a escolhida concorda < 40% e outra concorda ≥ 60% com apoio de ≥ 2 fontes, troca (aparece em CONSENSO no `report.txt` e na coluna `motivo` do `channel_check.csv`). Hoje: ESPN 5, HBO+, RIT e TNT Novelas saíram da Claro.
13. **Detector de grades idênticas entre canais diferentes** (≥ 85% dos títulos, ≥ 10 instantes): TV aberta e afiliadas (categorias em `categorias_rede_ok`) são isentas; pares já conferidos ficam em `identicas_ok` (Paramount+ 1–4 e USA/Syfy: todas as fontes concordam; TLC dos dois IDs). Qualquer par novo abre a issue `grades-identicas`. O `channel_check.csv` tem a coluna `nome_confere`; o `report.txt` lista ligações com nome diferente.
14. **Premiere 2–9 são canais de jogos:** as fontes (Claro, Open-EPG) só trazem "Hoje a partir das HH:MM – A x B" ou o nome do canal; não há grade confiável nas horas sem jogo. É limite das fontes, não ligação errada.

### Fontes avaliadas e descartadas
`epg.lat/files/br.xml.gz` (arquivo de 20/09, espelho do EPG_Share; o diretório ge.m3uiptv.com só lista links e mostra data errada), `globetvapp/epg` (parado desde 12/2025), `limaalef/BrazilTVEPG` (parado desde 19/09), `iptv-com/epg` (parado), open-epg `brazil2/5` (0 canais novos), guias prontos `iptv-org.github.io/epg/guides/br/*.xml` (404), i.mjh.nz Plex/Samsung BR (404), Roku (só 24h), EPG_Share ALL_SOURCES (enorme). **Os canais que ainda estão vazios (≈ 500 nomes) são séries/desenhos em loop 24h, adulto, PPV, eventos e afiliadas pequenas: nenhuma fonte brasileira testada os tem.**

### Como operar
- **Rodar o workflow:** Actions → *Atualizar EPG* → *Run workflow*, ou `POST /repos/RafaelAvigliano-Devops/EPG-IPTV/actions/workflows/epg.yml/dispatches` com `{"ref":"main"}` (precisa de token com escopo Actions; **guardar em `~/.service_env` (perm 600), nunca em arquivo versionado**). Depois: `python3 scripts/epgctl.py status` e `summary`.
- **Testar mudança no script sem credenciais:** servidor Xtream falso local (`player_api.php` com `user_info.auth=1` e `get_live_streams` com poucos streams; `xmltv.php` devolvendo `<tv></tv>`), copiar `scripts/`, `config.json` e `mapping.json` para uma pasta temporária e rodar `XTREAM_URL=http://127.0.0.1:PORTA XTREAM_USER=u XTREAM_PASS=p python3 scripts/build_epg.py`. Foi assim que as mudanças do dia foram validadas.
- **Rodar o scraper do mi.tv local:** `git clone --depth 1 https://github.com/iptv-org/epg && cd epg && npm install --ignore-scripts && npm run grab --silent -- --channels=sites/mi.tv/mi.tv_br.channels.xml --days=4 --maxConnections=8 --output=guide.xml` (~2 min).

### Segurança (pendente para o dono)
Tokens do GitHub da conta do dono aparecem **em texto puro em transcritos antigos de sessões** do Claude Code (`~/.claude/projects/…/*.jsonl`); 3 estão válidos. Um deles foi usado em 09/10, a pedido do dono, para disparar o workflow. **Rotacionar e apagar os transcritos**; criar token só de Actions do repo para uso futuro. Nenhum token foi gravado neste repositório.

### Pendências do dono
1. Conferir na TV o que a **ESPN 2** exibe (hoje: ESPN repetida com atraso de ~3 h via `ESPN2.br`).
2. Mandar exemplos de variantes que ainda aparecem erradas no TVLOK.
3. Rotacionar os tokens (acima).

### Ideias que ficaram
Relatório de divergências entre fontes no `report.txt`; usar `vivoplay`/`clarotvmais` no job do iptv-org como reserva extra; fixar o commit do `iptv-org/epg` se um scraper quebrar; cache da última cópia das fontes; painel `index.html` no Pages; fixar `ubuntu-24.04` no workflow antes de 19/10/2026 (o `ubuntu-latest` migra para o Ubuntu 26).
