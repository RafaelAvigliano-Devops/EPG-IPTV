# EPG-IPTV — guia para qualquer IA (e para humanos)

> **Leia também [HISTORICO.md](HISTORICO.md)**: o que foi feito, por quê, armadilhas aprendidas e como operar (inclui o dia 2026-10-09).

Projeto que gera um **EPG (XMLTV) próprio** para uma lista IPTV Xtream Codes e o publica via **GitHub Pages**, atualizado a cada 6 horas pelo GitHub Actions. Dono: Rafael (Canoas-RS, Brasil). Idioma de trabalho: **português do Brasil**.

## Regras que nunca mudam
- **Nunca** escreva usuário, senha, host do provedor ou o link do m3u4u em arquivo, commit, issue ou resposta. Eles vivem só nos **GitHub Secrets** (`XTREAM_URL`, `XTREAM_USER`, `XTREAM_PASS`, `M3U4U_EPG_URL` opcional) e em variáveis de ambiente locais. `.env` está no `.gitignore`.
- Não faça commit/push sem o dono pedir. Não abra pasta de chaves SSH nem tokens que não sejam do projeto.
- Não faça login em contas do dono (m3u4u, provedor, GitHub) nem digite senhas.

## URLs
- EPG (usar no app/TV): `https://rafaelavigliano-devops.github.io/EPG-IPTV/epg.xml`  (XML puro; o Pages já comprime na entrega)
- Relatórios publicados ao lado: `report.txt`, `channel_map.csv`, `channel_check.csv`
- Repositório: `git@github.com:RafaelAvigliano-Devops/EPG-IPTV.git` (público; Actions legíveis pela API pública)
- App do dono: **TVLOK** (campo "EPG URL override" = o link acima; "Additional EPG sources" só preenche canais sem grade, **não** substitui a do provedor).

## Arquitetura
```
Actions (cron 0 */6 * * *, ou "Run workflow")
  mitv:   (isolado, permissions: {}, continue-on-error) clona iptv-org/epg, `npm run grab` do mi.tv_br -> artefato mitv/guide.xml
  build:  baixa o artefato (opcional) + python scripts/build_epg.py -> docs/{epg.xml,report.txt,channel_map.csv,channel_check.csv,state.json}
  deploy: upload-pages-artifact(docs) + deploy-pages   (Pages Source = "GitHub Actions"; nada do EPG é commitado)
```
- `scripts/build_epg.py` (só stdlib): lê a lista Xtream (`player_api.php?action=get_live_streams`), baixa o XMLTV do provedor (`xmltv.php`) e as fontes de `config.json`, casa canais, gera o XML enxuto.
- `config.json`: `sources` (`url`, `url_env`, `type: claro` com `city`/`days`, ou `type: file` com `path`; `names_only` indexa só por nome), `min_hours_ahead`, `hours_past`(3), `days_ahead`(3), `desc_max`(120), `region_prefer` (["rs","rbs","poa","gaucha"]), `output`.
- `aliases` (em `config.json`): `{"nome do stream": "nome do canal na fonte"}`, para canais sem ID cujo nome não casa sozinho (ex.: "Record SP" → "RecordTV SP"). Valide o alvo nas fontes antes de incluir.
- `mapping.json`: correções manuais `{"id_do_provedor": "id_do_canal_na_fonte"}`.
- `scripts/epgctl.py`: diagnóstico **sem credenciais** (`status`, `channel <texto>`, `summary`).
- `docs/` é **gerado** e está no `.gitignore` (existe só no artefato do Pages).

## Como o casamento funciona (ordem de decisão por ID do provedor)
1. Nome dominante entre os streams que usam aquele `epg_channel_id` (`norm()` ignora FHD/HD/SD/4K/H265/ALT/BR/TV, acentos e pontuação; `+` vira "plus").
   Se o ID é compartilhado por canais de cidades diferentes e há um stream da região (`region_prefer`), esse nome vence.
2. Etapas, na ordem: `mapping.json` → casamento **por nome** nas fontes → casamento por **ID** igual. Em cada etapa vence a fonte com a **grade mais longa** (maior `stop`).
3. Streams **sem** `epg_channel_id`: irmão de variante (`vkey`: ignora qualidade e ordem das palavras) → nome nas fontes → senão "sem EPG".
4. O canal sai no XML com o **ID do provedor** (para o app casar por ID) e com todos os nomes dos streams como `display-name` (até 30) para apps que casam por nome.
- **Grade genérica perde para grade real:** `is_filler()` = ≤ 2 títulos distintos (ex.: "Premiere 2" o dia todo). Candidato com programação real vence mesmo com grade mais curta. Programas "No Data" (iptv-epg.org) são descartados na leitura da fonte (canal fica sem grade se for a única). Isso corrigiu Premiere 2/3/4, Canal do Boi/Rural, Rede Gospel, RIT e TV Aparecida, que mostravam o mesmo vazio.
- Programas são copiados (`slim`) só na janela [agora-3h, agora+3d] e só com title/sub-title/desc(120)/category/episode-num.
- Índice por nome ignora canais sem programação (já houve canal homônimo vazio escondendo o certo).

## Fontes (testadas, todas públicas e automáticas)
`provedor` (xmltv.php), EPG_Share BR/BR2/PT (`epgshare01.online/epgshare01/epg_ripper_*.xml.gz`), Pluto BR (`i.mjh.nz/PlutoTV/br.xml.gz`), `iptv-epg.org/files/epg-br.xml.gz`, `epg.pw/xmltv/epg_BR.xml`, Open-EPG `brazil1/3/4.xml.gz`.
- **Claro** (`type: claro`, cidade 190 = Canoas-RS): API Solr pública do site da Claro (`programacao.claro.com.br/gatekeeper`), 269 canais, só título+gênero, ~11 s e ~40k programas por execução (janela de `days` dias). **O WAF exige `q=` como 1º parâmetro e `:` sem codificar.** Traz as grades locais do RS (`claro.2063` Band HD, `claro.2091` SBT HD, `claro.2140` Globo RBS) usadas em `mapping.json`. IDs de saída: `claro.<id_canal>`.
- **mi.tv** (`type: file`, `names_only`, 09/10): job `mitv` do workflow clona `iptv-org/epg`, roda `npm run grab` só do `mi.tv_br` (825 canais, ~2 min, 610 com grade, 4 dias) e entrega `mitv/guide.xml` como artefato; o job `build` o lê como fonte. **Job isolado (`permissions: {}`, sem secrets) porque executa código de terceiros**; se falhar, o build segue sem ele (`fonte mi.tv ignorada`). `names_only`: indexa só por nome de exibição, porque o ID do site (`br#espn-1`) tem sufixos de desambiguação que colidem com canais numerados (ESPN Extra virava ESPN 1). Papel: reserva/conferência (perde para fontes com grade mais longa).
- **m3u4u** (REMOVIDO em 09/10, secret apagado; `scripts/check_m3u4u.py` e `monitoring/` ficaram obsoletos): XML gerado pelo site. Em 4 h ficou idêntico; ainda não se sabe se atualiza sozinho. Só entra se tiver a grade mais longa, então não atrapalha. Cobre canais que só ele tem (Sportynet, Premiere 1, Sony, USA Network...). A página m3u4u.com/epg é só catálogo (1.824 canais; `(m3u4u)` = base própria, `(src##)` = terceiros), sem URLs de fonte.
- Descartadas: EPG_Share ALL_SOURCES (enorme), m3u4me (precisa de servidor 24 h; o dono não tem).

## Limites conhecidos (não é bug do script)
- ~890 de 2.034 canais sem EPG: 24h/desenho/série, adulto, PPV, eventos, Cine Sky, afiliadas locais pequenas. Nenhuma fonte pública tem.
- **29 IDs repetidos pelo provedor** para canais diferentes (ex.: `globo.sp.br` = Globo SP + Sergipe; `sbt.rs.br` = SBT RJ/RS/RN). Um ID só tem uma grade → resolvido por `region_prefer` e `mapping.json`; o resto não tem solução só com EPG.
- Variantes **4K FHDR** vêm sem ID no provedor; só funcionam se o app casar por nome.
- SBT RS e Band RS: resolvidos pela Claro (`mapping.json` → `claro.2091`/`claro.2063`).
- Premiere 1: vem de Premiere Clubes via `aliases`. Premiere 2–9 só têm programa real em dia de jogo (nas outras horas todas as fontes dão título genérico).
- O deploy do Pages às vezes demora alguns minutos; não é erro.

## Saúde das fontes (anti-erro de fuso/divergência)
`source_health()` em `build_epg.py` compara cada fonte com as demais (título igual, mesmo canal, mesmo instante; títulos genéricos ignorados) e escreve a seção **SAUDE DAS FONTES** no `report.txt` (concordância, nº de comparações, melhor ajuste de fuso). Fuso errado é **corrigido automaticamente** (issue `fonte-fuso-<nome>`); fonte com < 15% é **isolada** (`fonte-divergente-<nome>`). Valores normais hoje: 67–73% (provedor, Claro, iptv-epg-br, open-epg, epgshare-br2). **Claro precisa de `-0300`** (horário local com sufixo Z). Ao incluir uma fonte nova, olhe essa seção antes de confiar nela.

## Keepalive (workflow agendado em repositório público)
O GitHub desativa workflows agendados após **60 dias sem atividade** no repositório público. Como o EPG sai pelo Pages (sem commits), `.github/workflows/keepalive.yml` roda **no dia 1 de cada mês** e commita `.keepalive` (data) como `epg-bot`. Custo do Actions: repositório público = runners gratuitos; uso real ~2,5 min por execução (~4 min cobrados se fosse privado) × 4/dia. Se um dia o EPG parar de atualizar sem aviso, conferir em Actions se os workflows foram desativados e reativá-los.

## Arquivos publicados e config de ajuste
- `epg.xml` (completo, ~5,5 MB) e **`epg-lite.xml`** (2 dias, só título, ~2,4 MB; recomendado para TV lenta): `https://rafaelavigliano-devops.github.io/EPG-IPTV/epg-lite.xml`.
- `config.json`: `fuso_conhecido` (fonte → horas), `fontes_curtas_ok` (sem aviso de fonte parada), `id_preferido` (ID repetido → nome que fica com a grade), `aliases`, `lite`, `identicas_ok`, `categorias_rede_ok`, `region_prefer`.

## Proteções contra ligação errada / guia divergente (build_epg.py)
Medida de qualidade = **concordância**: fração de instantes (próximas 24 h, de 30 em 30 min) em que o título da fonte escolhida é igual ao das outras fontes para o mesmo canal. Mede "as fontes dizem o mesmo", não "está certo". Análise completa em `HISTORICO.md` ("Análise: como evitar que o guia fique divergente").
- `source_health`: fuso e divergência **por fonte** (isola a que diverge, ex.: `epgshare-pt`).
- `fix_channel_shifts`: fuso errado só em alguns canais de uma fonte.
- `consensus_pick` (canais com ID **e** casados por nome): troca a escolhida quando (a) ela < 40% e outra ≥ 60% com ≥ 2 apoios, ou (b) **ponto fora da curva**: ela < 25% e outra ≥ 35% e +25 pontos. Entre as que concordam (≥ 60%, até 20 pontos do topo) vence a de **grade mais longa**. Grade genérica (`is_filler`) **não vota**. `mapping.json` nunca é trocado.
- **Medição por canal** no `report.txt`: `CONCORDANCIA POR CANAL` (verificados × não verificáveis; faixas ≥80/60–79/40–59/<40), `BAIXA CONCORDANCIA`, `MUDARAM DE FONTE desde a execução anterior`. O `state.json` guarda `canais: {id: [fonte, concordância]}`.
- Detector de grades idênticas + `nome_confere`: ver HISTORICO (itens 11–13); isenções em `config.json` (`categorias_rede_ok`, `identicas_ok`, `aliases`).
- **Coleta da Claro robusta:** páginas de 10 mil registros (≈ 1,3 MB; páginas de 40 mil falham) com 4 tentativas cada. O servidor da Claro falha com frequência (`IncompleteRead`); sem isso uma falha movia ~94 canais de fonte de uma vez.
- Antes de confiar em qualquer ligação nova, rode o gerador e leia no `report.txt`: SAUDE DAS FONTES, CONSENSO, LIGACOES COM NOME DIFERENTE, GRADES IDENTICAS e as seções de concordância.
- Teste local sem credenciais: ver "Como operar" no `HISTORICO.md`; `EPG_PREV_STATE_FILE=<state.json>` simula o estado da execução anterior.

## Avisos automáticos (issues)
`build_epg.py` gera `alerts/alerts.json` (`{"completo": bool, "alertas":[{key,title,body,repeat}]}`); o passo "Avisos por issue" do workflow abre/atualiza/fecha **issues com a label `epg-alerta`** (uma por `key`; o GitHub envia e-mail ao abrir). Se o aviso some numa execução completa, a issue é fechada sozinha.
- `provedor-fora`: Xtream não responde (3 tentativas, `EPG_RETRY_WAIT` em segundos, padrão 30). **Não publica**: o EPG anterior continua no ar. Comenta a cada execução.
- `credenciais`: `auth` != 1 ou lista vazia (senha/usuário trocados). Também não publica.
- `conta-expira`: `exp_date` do provedor em ≤ 15 dias (ou vencida); `conta-status`: status != Active.
- `lista-mudou`: canais caíram abaixo de 70% da execução anterior.
- `fonte-fora-<nome>` (falhou em 2 execuções seguidas) e `fonte-parada-<nome>` (grade < 24 h à frente em 2 execuções seguidas). O estado entre execuções vai em `docs/state.json` (publicado no Pages e lido na próxima execução).
- `favoritos`: canais de `config.json → favoritos` (substring do nome) sem EPG em ≥ 50% dos streams ou com grade acabando em < 12 h.
- `fonte-fuso-<nome>` (fuso corrigido automaticamente), `fonte-divergente-<nome>` (fonte isolada/baixa concordância).
- `grades-identicas`: canais diferentes com a mesma grade (provável ligação errada).
- `canais-regrediram` (concordância do canal caiu ≥ 40 pontos desde a execução anterior) e `baixa-concordancia` (fonte final < 40% de concordância com ≥ 3 fontes): ver "Análise" no HISTORICO.md.
- `telas-menos`: `max_connections` do provedor menor que `telas_esperadas` (config.json, hoje 4). A 1ª linha do `report.txt` mostra "Conta: status · telas contratadas · em uso agora · vence em" (só números, sem usuário/senha/host); `epgctl.py summary` a exibe.
- `sem-fontes`, `script-falhou`.
Testado localmente com servidor Xtream falso (conta vencendo, favoritos, provedor fora). A parte JavaScript do workflow só roda no GitHub.

## Operação
```bash
python3 scripts/epgctl.py status            # Actions + arquivo publicado
python3 scripts/epgctl.py channel espn      # fonte, grade, agora/depois
python3 scripts/epgctl.py summary
# rodar o gerador localmente (credenciais só na sessão, nunca em arquivo):
XTREAM_URL=... XTREAM_USER=... XTREAM_PASS=... [M3U4U_EPG_URL=...] python3 scripts/build_epg.py
```
- Depois de **qualquer** push, o site só muda quando o workflow roda (Actions → Atualizar EPG → Run workflow, ou próxima execução agendada). Push não dispara o workflow.
- Conferir o resultado: `status` (run verde, deploy verde, Last-Modified novo) e `channel`.
- Erro no passo "Gerar EPG": o log completo exige login; reproduza localmente apagando `docs/` e rodando o script (já houve falha por pasta inexistente).

## Receitas
- **Dois canais com a mesma grade:** comparar as fontes (`channel_check.csv` mostra a fonte usada). Se a fonte é genérica ("No Data", título único) já é tratada por `is_filler`; se for rede com afiliadas, é esperado. Se uma fonte divergir das outras, fixe a boa em `mapping.json`.
- **Canal sem casamento por nome** (ex.: "RECORD SP" × "RecordTV SP"): adicionar em `aliases` (config.json) depois de conferir o alvo e a data final nas fontes.
- **Canal com grade errada/ausente:** `epgctl.py channel <nome>` → ver `fonte`/`id_na_fonte`. Se o canal certo existe em alguma fonte com outro nome, adicione em `mapping.json` e rode o gerador. Se o ID é compartilhado, ajuste `region_prefer`/`mapping.json`.
- **Nova fonte de EPG:** teste antes (baixa? quantos canais? até que data? quantos casam com `channel_map.csv`), depois uma linha em `config.json`. Fonte com URL secreta usa `url_env` + secret + linha em `.github/workflows/epg.yml`.
- **Arquivo pesado/lento no app:** reduzir `days_ahead`/`desc_max` em `config.json` (hoje ~6,6 MB, ~0,9 MB comprimido).
- Ao mudar o script, rodar localmente e conferir `docs/report.txt` (resumo no topo) antes de commitar; commits terminam com a linha `Co-Authored-By` exigida pelo ambiente.

## Histórico de decisões (resumo)
Fonte única do provedor estava velha → múltiplas fontes, vence a grade mais longa → bug de elementos XML compartilhados (HBO sem grade) corrigido com cópia por canal → app TVLOK ignorava a fonte adicional (usar override) → arquivo de 16 MB/gz lento → XML enxuto sem gz → histórico git crescia → Pages via Actions → IDs errados/repetidos do provedor → casamento por nome primeiro + região RS → variantes 4K irmãs.

## Estado atual (2026-10-15) e como continuar
- **Cobertura:** 1.162 de 2.034 canais com EPG (872 sem: séries/desenhos 24h, adulto, PPV, eventos, afiliadas pequenas; nenhuma fonte brasileira testada os tem). A cobertura quase não mudou desde 09/10; o trabalho foi de **qualidade** (ver `HISTORICO.md`).
- **Fontes ativas:** provedor, EPG_Share (br/br2/pt), Pluto, iptv-epg.org, epg.pw, Open-EPG (1,2,3,4,6,7), **Claro** (Canoas-RS, paginada), **mi.tv** (job isolado). m3u4u removido.
- **Conta (15/10):** usuário/link trocados pelo dono (os antigos iam expirar), Secrets atualizados; ativa, vence em 16/10/2027; **licença com 3 telas** (`report.txt` 1ª linha). `telas_esperadas: 4` em `config.json` gera a issue `telas-menos` — dono deve conferir com o provedor ou ajustar para 3.
- **Último run conhecido:** `38791833643` (15/10 19:11 UTC) verde nos 3 jobs. Consenso trocou 5 canais (HBO+, HGTV, RIT, TNT Novelas, TV Câmara). Correção posterior `0351736` (grade genérica não vota) ainda **não medida no Actions**: próximo run agendado 00:00 UTC; conferir se a issue `baixa-concordancia` encolheu (esperado: sem os Premiere).
- **Issues abertas em 15/10:** 13 `baixa-concordancia` (Premiere = falso positivo já corrigido; reais: TV Escola, TVE, Ideal TV, HGTV), 12 `telas-menos`, 10 `grades-identicas` (Premiere HD 2 = Premiere 3 etc.: mesmo jogo em vários canais; ESPN 5 ≈ ESPN 6 vale olhar), 3 `fonte-divergente-epgshare-pt` (isolada automaticamente, ok).
- **Pendências do dono:** (1) conferir na TV o que a **ESPN 2** exibe (hoje ESPN repetida com ~3 h de atraso via `ESPN2.br`; `mapping.json` fixa `espn.2.br`); (2) mandar exemplos de variantes que ainda aparecem erradas no TVLOK; (3) resolver 3 × 4 telas; (4) **rotacionar os tokens do GitHub** que estão em texto puro em transcritos antigos de sessão do Claude Code e criar um token só de Actions em `~/.service_env`.
- **Sem solução em fonte pública:** Globo Rede Amazônica/EPTV Araraquara/Band RN/SBT regionais, Fórmula 1, Agro Canal, Sportynet 02/03 (só o m3u4u tinha), Gazeta Alagoas/Norte ES.
- **Descartadas:** `epg.lat` (arquivo velho, espelho do EPG_Share), `globetvapp/epg`, `limaalef/BrazilTVEPG`, `iptv-com/epg`, open-epg `brazil2/5`, guias prontos iptv-org (404), Plex/Samsung/Roku.
- **Risco conhecido:** a API da Claro não é documentada e pode mudar/bloquear (WAF exige `q=` como 1º parâmetro, `:` sem codificar, data com segundos); `guiadetv.com` e `meuguia.tv` (iptv-org) estão quebrados.

### Fontes em tempo real avaliadas (09/10)
- **iptv-org/epg** (ativo, commit 08/10): scrapers de sites; roda no Actions com Node (`npm install --ignore-scripts` ≈ 7 s, `npm run grab -- --channels=<xml> --days=3` ≈ 4 s para 10 canais). Sites BR: `mi.tv` (547 canais), `guiadetv.com` (123), `meuguia.tv` (101), `clarotvmais.com.br` (158), `vivoplay.com.br` (361). Os guias prontos `iptv-org.github.io/epg/guides/br/*.xml` estão **fora do ar (404)**; `limaalef/BrazilTVEPG` parado desde 19/09; `iptv-com/epg` parado desde 03/2026.
- **Teste real dos scrapers (09/10, 3 dias, `--maxConnections=10`):** `mi.tv` OK (10 canais em 4 s; 825 no BR), `vivoplay` OK (157 canais com grade, 18 mil programas, 56 s, até 13/10), `clarotvmais` OK (150 canais, 15,6 mil programas, 31 s, até 12/10), **`guiadetv.com` e `meuguia.tv` quebrados (0 programas, site mudou)**. Rodar no Actions é viável (Node + `npm install --ignore-scripts` ≈ 7 s + clone raso ≈ 157 MB).
- **Nenhum desses sites cobre os canais que ainda estão vazios** (só "Premiere 2 -"): os 499 nomes restantes são séries/desenhos em loop 24h e afiliadas pequenas. Servem como **conferência independente e redundância**, não para ampliar cobertura. mi.tv confirmou o padrão da ESPN 2.
- Auditoria da Claro (100 canais): grade bate com outra fonte em todos, exceto ESPN 2.

### Backlog de melhorias (ideias, nada disso está feito)
0. (feito 09/10) mi.tv via iptv-org/epg. Falta: relatório de **divergências** entre fontes (mi.tv × escolhida) no `report.txt`; considerar `vivoplay`/`clarotvmais` no mesmo job; fixar o commit do iptv-org/epg se o scraper quebrar por mudança upstream.
1. **Painel** `index.html` no Pages com resumo, status das fontes, favoritos e problemas.
2. **Diff entre execuções**: avisar quando um canal favorito muda de fonte ou perde programas (mudança de ID no provedor); listar "canais novos sem EPG".
3. **Cache das fontes**: se uma fonte pública cai, reaproveitar a última cópia (hoje só se perde o canal naquela execução).
4. **Mais fontes** para canais sem grade (afiliadas regionais, Cine Sky, Sportynet, Premiere 1); testar cobertura antes de incluir.
5. **Lista de favoritos** mais refinada (por ID e por nome exato) e limiares de aviso configuráveis em `config.json`.
6. Fixar `ubuntu-24.04` no workflow (o `ubuntu-latest` migra para o Ubuntu 26 em 19/10/2026) e atualizar as actions para versões Node 24 quando houver.
7. Reduzir o histórico de aviso de "fonte parada" para fontes que o dono considera descartáveis (ex.: remover Pluto do `config.json`).

8. **Cache das fontes** também vale para a Claro (21 MB só com janela longa; hoje busca janela curta, ~11 s).
9. Verificar periodicamente se a API da Claro mudou (WAF exige `q=` como 1º parâmetro; sem termo de uso público).

### Como registrar o trabalho
Ao terminar uma melhoria: atualizar este arquivo (arquitetura, limites, backlog e "Estado atual"), rodar o gerador localmente, pedir confirmação ao dono, commitar e rodar o workflow; conferir com `python3 scripts/epgctl.py status|summary`.
