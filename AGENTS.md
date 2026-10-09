# EPG-IPTV — guia para qualquer IA (e para humanos)

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
  build:  python scripts/build_epg.py  -> docs/{epg.xml,report.txt,channel_map.csv,channel_check.csv}
  deploy: upload-pages-artifact(docs) + deploy-pages   (Pages Source = "GitHub Actions"; nada do EPG é commitado)
```
- `scripts/build_epg.py` (só stdlib): lê a lista Xtream (`player_api.php?action=get_live_streams`), baixa o XMLTV do provedor (`xmltv.php`) e as fontes de `config.json`, casa canais, gera o XML enxuto.
- `config.json`: `sources` (url ou `url_env`), `min_hours_ahead`, `hours_past`(3), `days_ahead`(3), `desc_max`(120), `region_prefer` (["rs","rbs","poa","gaucha"]), `output`.
- `mapping.json`: correções manuais `{"id_do_provedor": "id_do_canal_na_fonte"}`.
- `scripts/epgctl.py`: diagnóstico **sem credenciais** (`status`, `channel <texto>`, `summary`).
- `docs/` é **gerado** e está no `.gitignore` (existe só no artefato do Pages).

## Como o casamento funciona (ordem de decisão por ID do provedor)
1. Nome dominante entre os streams que usam aquele `epg_channel_id` (`norm()` ignora FHD/HD/SD/4K/H265/ALT/BR/TV, acentos e pontuação; `+` vira "plus").
   Se o ID é compartilhado por canais de cidades diferentes e há um stream da região (`region_prefer`), esse nome vence.
2. Etapas, na ordem: `mapping.json` → casamento **por nome** nas fontes → casamento por **ID** igual. Em cada etapa vence a fonte com a **grade mais longa** (maior `stop`).
3. Streams **sem** `epg_channel_id`: irmão de variante (`vkey`: ignora qualidade e ordem das palavras) → nome nas fontes → senão "sem EPG".
4. O canal sai no XML com o **ID do provedor** (para o app casar por ID) e com todos os nomes dos streams como `display-name` (até 30) para apps que casam por nome.
- Programas são copiados (`slim`) só na janela [agora-3h, agora+3d] e só com title/sub-title/desc(120)/category/episode-num.
- Índice por nome ignora canais sem programação (já houve canal homônimo vazio escondendo o certo).

## Fontes (testadas, todas públicas e automáticas)
`provedor` (xmltv.php), EPG_Share BR/BR2/PT (`epgshare01.online/epgshare01/epg_ripper_*.xml.gz`), Pluto BR (`i.mjh.nz/PlutoTV/br.xml.gz`), `iptv-epg.org/files/epg-br.xml.gz`, `epg.pw/xmltv/epg_BR.xml`, Open-EPG `brazil1/3/4.xml.gz`.
- **m3u4u** (opcional, secret): XML gerado pelo site. Em 4 h ficou idêntico; ainda não se sabe se atualiza sozinho. Só entra se tiver a grade mais longa, então não atrapalha. Cobre canais que só ele tem (Sportynet, Premiere 1, Sony, USA Network...). A página m3u4u.com/epg é só catálogo (1.824 canais; `(m3u4u)` = base própria, `(src##)` = terceiros), sem URLs de fonte.
- Descartadas: EPG_Share ALL_SOURCES (enorme), m3u4me (precisa de servidor 24 h; o dono não tem).

## Limites conhecidos (não é bug do script)
- ~890 de 2.034 canais sem EPG: 24h/desenho/série, adulto, PPV, eventos, Cine Sky, afiliadas locais pequenas. Nenhuma fonte pública tem.
- **29 IDs repetidos pelo provedor** para canais diferentes (ex.: `globo.sp.br` = Globo SP + Sergipe; `sbt.rs.br` = SBT RJ/RS/RN). Um ID só tem uma grade → resolvido por `region_prefer` e `mapping.json`; o resto não tem solução só com EPG.
- Variantes **4K FHDR** vêm sem ID no provedor; só funcionam se o app casar por nome.
- SBT RS e Band RS só têm grade curta (Open-EPG).
- Premiere 1: nenhuma fonte pública.
- O deploy do Pages às vezes demora alguns minutos; não é erro.

## Tarefa pendente: validar se o link do m3u4u se atualiza sozinho (verificar ~10h de Brasília de 2026-10-09)
Contexto: o secret `M3U4U_EPG_URL` é um XML gerado no site do m3u4u. Em 2026-10-09 ele ficou **byte a byte idêntico** por ~4 h (7.356.083 bytes, 246 canais, grade de 07/10 01:00 a 11/10 07:13 UTC). Baseline em `monitoring/m3u4u_baseline.json`.
Como validar (não precisa do link):
1. `python3 scripts/epgctl.py summary` — a linha `m3u4u` mostra "grade da fonte até DD/MM HH:MM UTC" da última execução do Actions. Se for **depois de 11/10 07:13** → o link é **vivo** (manter). Se continuar em **11/10 07:13** (e já passou de 10 h do dia 09) → **congelado**.
2. Rode o workflow (ou espere o agendado) antes, para o report refletir o momento: `python3 scripts/epgctl.py status`.
3. Com o link (o dono informa na sessão, nunca gravar): `M3U4U_EPG_URL='<link>' python3 scripts/check_m3u4u.py` compara com o baseline e dá o veredito.
Decisão: vivo → manter o secret; congelado → o dono pode apagar o secret `M3U4U_EPG_URL` (o resto do projeto não depende dele). Registrar o resultado aqui.

## Avisos automáticos (issues)
`build_epg.py` gera `alerts/alerts.json` (`{"completo": bool, "alertas":[{key,title,body,repeat}]}`); o passo "Avisos por issue" do workflow abre/atualiza/fecha **issues com a label `epg-alerta`** (uma por `key`; o GitHub envia e-mail ao abrir). Se o aviso some numa execução completa, a issue é fechada sozinha.
- `provedor-fora`: Xtream não responde (3 tentativas, `EPG_RETRY_WAIT` em segundos, padrão 30). **Não publica**: o EPG anterior continua no ar. Comenta a cada execução.
- `credenciais`: `auth` != 1 ou lista vazia (senha/usuário trocados). Também não publica.
- `conta-expira`: `exp_date` do provedor em ≤ 15 dias (ou vencida); `conta-status`: status != Active.
- `lista-mudou`: canais caíram abaixo de 70% da execução anterior.
- `fonte-fora-<nome>` (falhou em 2 execuções seguidas) e `fonte-parada-<nome>` (grade < 24 h à frente em 2 execuções seguidas). O estado entre execuções vai em `docs/state.json` (publicado no Pages e lido na próxima execução).
- `favoritos`: canais de `config.json → favoritos` (substring do nome) sem EPG em ≥ 50% dos streams ou com grade acabando em < 12 h.
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
- **Canal com grade errada/ausente:** `epgctl.py channel <nome>` → ver `fonte`/`id_na_fonte`. Se o canal certo existe em alguma fonte com outro nome, adicione em `mapping.json` e rode o gerador. Se o ID é compartilhado, ajuste `region_prefer`/`mapping.json`.
- **Nova fonte de EPG:** teste antes (baixa? quantos canais? até que data? quantos casam com `channel_map.csv`), depois uma linha em `config.json`. Fonte com URL secreta usa `url_env` + secret + linha em `.github/workflows/epg.yml`.
- **Arquivo pesado/lento no app:** reduzir `days_ahead`/`desc_max` em `config.json` (hoje ~6,6 MB, ~0,9 MB comprimido).
- Ao mudar o script, rodar localmente e conferir `docs/report.txt` (resumo no topo) antes de commitar; commits terminam com a linha `Co-Authored-By` exigida pelo ambiente.

## Histórico de decisões (resumo)
Fonte única do provedor estava velha → múltiplas fontes, vence a grade mais longa → bug de elementos XML compartilhados (HBO sem grade) corrigido com cópia por canal → app TVLOK ignorava a fonte adicional (usar override) → arquivo de 16 MB/gz lento → XML enxuto sem gz → histórico git crescia → Pages via Actions → IDs errados/repetidos do provedor → casamento por nome primeiro + região RS → variantes 4K irmãs.

## Estado atual (2026-10-09) e como continuar
- Último resultado conhecido: **1.140 de 2.034 canais com EPG** (1.000 por ID do provedor, 129 por nome, 11 por variante irmã); 894 sem EPG em nenhuma fonte. 12 fontes ativas (11 públicas + provedor; m3u4u opcional entrega ~30 canais).
- Avisos por issue implementados (seção acima); o passo JavaScript do workflow ainda **não foi visto rodando** no Actions: na primeira execução depois do push, conferir se o passo "Avisos por issue" ficou verde e se as issues (label `epg-alerta`) fazem sentido. Esperado: aviso de `fonte-parada-pluto-br` (grade termina em 09/10); a conta vence em 28/10/2026 (aviso a partir de 13/10).
- Pendência: validar se o link do m3u4u se atualiza (seção "Tarefa pendente", ~10 h de 09/10).
- Pendência do dono: mandar exemplos concretos de variantes (ex.: "ESPN 2") que ainda aparecem erradas no TVLOK; os dados do XML mostram todas as variantes com a mesma grade, então pode ser comportamento do app.

### Backlog de melhorias (ideias, nada disso está feito)
1. **Painel** `index.html` no Pages com resumo, status das fontes, favoritos e problemas.
2. **Diff entre execuções**: avisar quando um canal favorito muda de fonte ou perde programas (mudança de ID no provedor); listar "canais novos sem EPG".
3. **Cache das fontes**: se uma fonte pública cai, reaproveitar a última cópia (hoje só se perde o canal naquela execução).
4. **Mais fontes** para canais sem grade (afiliadas regionais, Cine Sky, Sportynet, Premiere 1); testar cobertura antes de incluir.
5. **Lista de favoritos** mais refinada (por ID e por nome exato) e limiares de aviso configuráveis em `config.json`.
6. Fixar `ubuntu-24.04` no workflow (o `ubuntu-latest` migra para o Ubuntu 26 em 19/10/2026) e atualizar as actions para versões Node 24 quando houver.
7. Reduzir o histórico de aviso de "fonte parada" para fontes que o dono considera descartáveis (ex.: remover Pluto do `config.json`).

### Como registrar o trabalho
Ao terminar uma melhoria: atualizar este arquivo (arquitetura, limites, backlog e "Estado atual"), rodar o gerador localmente, pedir confirmação ao dono, commitar e rodar o workflow; conferir com `python3 scripts/epgctl.py status|summary`.
