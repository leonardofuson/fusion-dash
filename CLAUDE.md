# fusion-dash — Portal BI

> Dashboards de **consumo** de dados. Schema do Supabase em [SCHEMA.md](../SCHEMA.md). Dash **Compras** (sistema de input de OC/OP, fundamentalmente diferente) em [COMPRAS.md](COMPRAS.md).

## Arquitetura

- Login via Supabase Auth → JWT → PostgREST com RLS
- Catálogo de dashes hardcoded em `auth.js` (objeto `DASHES`)
- Cada dash usa `fusionAuth.requireAuth('key')` como gate
- Dashes ativos: `lojas`, `ecommerce`, `diretoria`, `estoque`, `financeiro`, `compras`, `simulador`
- Padrão de fetch: 1 chamada em `vw_pedidos_full` (view UNION ALL + schema padronizado). **Antes 31/05/2026**: 2 chamadas paralelas a `pedidos` + `pedidos_historico` com `.concat()`. Tabelas físicas foram unificadas em `pedidos` única (473k rows, out/24→hoje); `pedidos_historico` virou backup `pedidos_historico_archived_20260531` (drop previsto 7-30d pós-estabilidade).
- RLS em tudo (`pedidos`, `produtos`, `estoque`, `contas_pagar`, `user_roles`, `metas_lojas`) — sem login = sem dado

## Comandos
```bash
cd fusion-dash
# Abrir qualquer .html direto no browser para testar
# Deploy: git push origin main (auto-deploy Render)
```

## Comportamento de sessão (auth.js)

SDK inicializado com `{ persistSession: true, autoRefreshToken: true, detectSessionInUrl: false }`. Consequências:
- Sessão persiste em `localStorage` entre reloads, abas, fechamentos
- Token renova **automaticamente em background (~50min)** — usuário não relogga durante o dia
- Logout só por: clique em "Sair" OU expiração do refresh token (~30 dias de inatividade)
- Por design — se alguém reclamar "por que não me desloga?", é intencional

## ⚠️ JWT autoRefresh — não capturar AUTH_HEADERS estaticamente

Token JWT expira em ~1h. **Não usar `var AUTH_HEADERS = auth.headers` capturado uma vez no load** — em sessões longas (form de cadastro multi-cor, etc) o POST sai com token expirado → `401 PGRST303 "JWT expired"`. Padrão em [compras.html](compras.html#L568) (24/04/2026): função async `getAuthHeaders()` lê `session.access_token` fresh via `fusionAuth.getSession()` antes de cada request. Aplicar nos demais dashes se aparecer 401 PGRST303.

## Configuração Supabase Auth (crítico)

- **Provider Email:** habilitado
- **Confirm email: DESLIGADO** — usuário criado no painel admin já nasce confirmado
- Secure email change / Secure password change: ligados (default)
- **Minimum password length: 6**

> ⚠️ **NÃO reativar "Confirm email"** sem ajustar o procedimento de criar usuário — se ligado, o botão "Add user" passa a exigir confirmação por e-mail e quebra o fluxo.

## Cadastro de usuários no dash

**Via Supabase Dashboard** (recomendado — UI guiada):
1. Authentication → Users → **Add user → Create new user**
2. Preencher e-mail + senha (mínimo 6 chars)
3. **Marcar checkbox "Auto Confirm User"** ← crítico; sem isso o usuário nasce "unconfirmed" e não consegue logar
4. **Create user** → copiar o User UID
5. SQL Editor:
   ```sql
   INSERT INTO user_roles (user_id, email, nome, role, dashes) VALUES
     ('UID-AQUI', 'pessoa@usefusion.com.br', 'Nome', 'diretoria',
      ARRAY['lojas','estoque']);
   ```

**Via API admin** (script):
1. `POST {SUPABASE_URL}/auth/v1/admin/users` com `email`, `password`, `email_confirm: true`, `user_metadata: {nome}` (requer `SUPABASE_KEY` service_role do `.env`)
2. `POST {SUPABASE_URL}/rest/v1/user_roles` com `user_id`, `email`, `nome`, `role`, `dashes` (array), `ativo: true`

- Roles usados: `diretoria`, `gerente`, `gestor` (campo livre, não controla acesso — quem controla é `dashes[]` + `ativo`)
- Dashes disponíveis: `lojas`, `ecommerce`, `diretoria`, `estoque`, `compras`, `financeiro`
- Senha padrão inicial: `projetomax` (orientar troca no primeiro acesso)

## Adicionar novo dashboard (procedimento)

> **Portal redesenhado (10/07/2026)**: `index.html` renderiza os cards **agrupados por categoria** (`cat` no DASHES: `vendas`/`operacoes`/`inteligencia`/`assistente`), cada card com a **inicial cropada** + fundo em **fade na cor da categoria** (Vendas azul, Operações verde, Inteligência roxo, Assistente cinza) + texto em negativo. **Sem emojis** — o campo `icone` continua no DASHES mas o card não usa mais. Cores/labels/ordem das categorias em `CAT_META` no `index.html`. `Projetos` foi removido do catálogo. `restritoPara` + gating por `user_roles.dashes` inalterados. Sandbox de estilos (não versionado, na raiz do workspace): `portal-preview.html`.

Pra criar um novo dash (ex: `marketing`):
1. Editar `auth.js` — adicionar entry no objeto `DASHES` **com `cat`** (define a seção/cor no portal):
   ```js
   marketing: { titulo: 'Marketing', descricao: 'Campanhas e CAC', url: '/marketing.html', icone: '📣', cat: 'inteligencia' }
   ```
2. Criar `marketing.html` — copiar `compras.html` como template, trocar label da topbar e `fusionAuth.requireAuth('marketing')`
3. Liberar acesso nos usuários que devem ver:
   ```sql
   UPDATE user_roles SET dashes = array_append(dashes, 'marketing')
   WHERE role = 'diretoria';
   ```
4. Commit + push em `main` → Render auto-deploy

## Convenções compartilhadas (todos os dashes de consumo)

- **Charts**: `.destroy()` antes de recriar (objeto `CHARTS = {}` global). Sparklines em arrays próprios.
- **Cores oficiais** em `LOJA_CORES` no `auth.js` — não inventar.
- **Datas**: fuso `America/Sao_Paulo` em todo agrupamento.
- **Período default = MTD (Este Mês)**: chip `mtd` com classe `on` no HTML, init JS com `DE=inicioMesSP();ATE=h;`. Decisão padrão da Fusion (29/04/2026) — diretoria pensa em mês corrente. Não usar 30d/7d como default.
- **Chip "Último Mês" (preset `m-1`)**: M-1 fechado (dia 01 ao último dia do mês anterior). Posicionado entre "Este Mês" e "Este Ano". Implementação: `ate=somaDias(inicioMesSP(),-1); de=ate.slice(0,7)+'-01'`. Em `lojas.html`, `ecommerce.html` e `diretoria.html` (02/05/2026).
- **Pedidos**: 1 fetch em `vw_pedidos_full` (UNION ALL no servidor + schema padronizado, inclui `fee_canal_fonte`). Sempre filtrar `status NOT IN ('cancelado', 'devolvido')` em receita.
- **Mobile**: breakpoint principal 768px. Cards empilhados em mobile, lado-a-lado em desktop.
- ⚠️ **KPI sempre numa linha só (`white-space:nowrap`)**: o valor de KPI (`R$ 16.758.883`, `29,1%`, etc) **nunca** pode quebrar o símbolo monetário pro número em linha separada. A classe do valor (`.kpi-val`, `.kpi-value`, `.kpi9 .val`…) **DEVE** ter `white-space:nowrap`. Regra universal — vale pra todo dash e todo KPI novo. ⚠️ Como o card costuma ter `overflow:hidden`, `nowrap` num layout apertado (muitas colunas × valores na casa dos milhões) **corta** o número em vez de quebrar — então, se o maior valor não couber na coluna mais estreita, reduzir `font-size` do valor e/ou o padding lateral do card até caber (validar com render headless, não no olho). Caso real: `ecommerce.html` aba Mensal "Este Ano" com 7 colunas — `R$ 16.758.883` cortava; fix = `.kpi-val` 1.5→1.45rem + `.kpi` padding `18px`→`18px 14px` (22/06/2026). Demais dashes (≤6 col ou valores menores) só precisaram do `nowrap`.
- **Export PNG**: html2canvas. Aplicar em todo card de KPI relevante.
- ⚠️ **Não usar `display:flex` num container cujo texto tem `<b>`/`<span>` inline soltos** (ex: callout `.note`): cada elemento inline vira um flex item próprio → a frase fatia em colunas verticais. Pra ícone+texto num callout, usar `position:relative` no container + ícone `position:absolute` + `padding-left` reservando o espaço (texto flui como prosa normal). Bug 17/06/2026 no `marketing.html .note`.

## Padrão de performance — Progressive load + cache + lazy (01/06/2026)

Padrão aplicado em 6 dashes (lojas, ecommerce, diretoria, financeiro, cockpit, estoque). Catálogo de MVs em [`../SCHEMA.md > Performance`](../SCHEMA.md#performance--materialized-views--índice-composto-01062026).

### 1. MV agregada por dia (progressive load)

Cada dash que consome `pedidos` em janelas grandes tem MV dedicada agregada por `data_pedido` (cobre 365d). Dashboard busca a MV PRIMEIRO (200-700ms, ~600-4k linhas) e pinta **KPIs + Pareto + Top Produtos imediato** via `renderKPIsImediato(curMV, prevMV)` + `renderTopProdutosImediato(mvSku)`. Em paralelo dispara `fetchPedidos()` detalhado pra rankings/PA/sparklines/drilldowns — quando chega, `renderAll()` completo sobrescreve.

- **lojas.html**: `mvw_lojas_dia` + `mvw_lojas_sku_dia` (Top Produtos) + `mvw_lojas_vend_dia` (preparada, integração pendente). TTFP 12m: **20s → 0.6s (33x)**.
- **ecommerce.html**: `mvw_ecommerce_canal_dia` (KPIs + Waterfall) + **`mvw_ecommerce_sku_dia`** (09/06: lista de produtos + KPI Unidades no paint imediato; receita/qtd/cmv por sku_pai/dia/canal) + **`mvw_ecommerce_geo_dia`** + **`mvw_ecommerce_pgto_dia`** (09/06: geo UF/cidade + métodos/parcelas no paint imediato; antes ficavam vazios até o fetch de 10-115k pedidos chegar). `montarSkuGroups()` usa a MV até os itens carregarem (background → drawer/variantes/fee-dev-frete rateado + CMV real). Geo/pgto: `renderGeoMV`/`renderPaymentsMV` reusam `pintarGeo`/`pintarPayments` (HTML idêntico ao caminho dos pedidos), aplicam focusCanal+canaisSel client-side; receita = `valorReceita` (frete só p/ ML). Todas as MVs replicam EXATAMENTE a cláusula `ped` (dedup fio+tiktok/confec+shopify, exclui cancelado+devolvido) — validado A/B (0 divergências em SKU, UF, cidade, método, parcela). DDL `sql/2026-06-09_mvw_ecommerce_sku_dia.sql` + `sql/2026-06-09_mvw_ecommerce_geo_pgto_dia.sql`; refresh no cron de enriquecimento. **Cache localStorage** guarda mv+sku+geo+pgto → revisit (≤5min) pinta KPIs+waterfall+lista+geo+pgto instant. Outras otimizações 09/06 no `buscarTudo`: **paginação paralela** (página 0 → se cheia, ondas paralelas) — corta o fetch serial de `vw_pedidos_full`; `fetchItensForIds` 5→8 batches paralelos. Lista popula ~2,8s vs ~6,6s; geo pinta ~2,1s vs ~4,5s; load completo ~12s→~6s.
- **diretoria.html**: `mvw_diretoria_dia` (TODAS origens, agregação client-side por origem/canal/loja). **98x speedup** (247s → 2.5s em 12m) — descobriu bug oculto: `vw_pedidos_full?limit=100000` era truncado em 1000 pelo PostgREST, dash mostrava só primeiros 1000 sem ninguém notar.

### 2. Cache localStorage (TTL 5min)

Cada dash tem chave própria pra evitar colisão. Cache pinta dashboard IMEDIATAMENTE antes do fetch; refresh fresh roda em background e re-renderiza. Quota total ~5MB no pior caso (todos os 6 cacheados juntos), dentro do limite Chrome (5-10MB).

| Dash | Chave | Conteúdo cacheado |
|---|---|---|
| lojas | `lojas_v2_<de>_<ate>` | `{mv, mvPrev, sku}` da `mvw_lojas_dia` + `_sku_dia` |
| ecommerce | `ecomm_v1_<de>_<ate>` | `{mv, mvPrev}` da `mvw_ecommerce_canal_dia` |
| diretoria | `diretoria_v2_<de>_<ate>` | `{cur, prev}` rows da `mvw_diretoria_dia` (período atual + anterior pra Δ%) |
| financeiro | `financeiro_contas_v1` | rows de `contas_pagar` (cap 8000 pra prevenir QuotaExceeded) |
| cockpit | `cockpit_data_v1` | `{dre, proj, entradasCaixa, saldosBancarios}` (~1MB) |
| estoque | `estoque_data_v1` | `{prods, est, vendaItens}` (3 datasets) |

Helpers padronizados: `cacheKey()`, `cacheGet()`, `cacheSet()` no início do `<script>`. TTL 5min é seguro pra operação intra-dia (dados mudam pouco; refresh recupera fresh em background).

### 3. Lazy load de charts pesados

`requestIdleCallback` (fallback `setTimeout(0)`) defere Chart.js do critical render path. Em janelas grandes esses charts somam 500-1000ms de bloqueio JS — KPIs/tabelas pintam imediato, charts entram quando o browser respira.

- **lojas.html** `renderAll()`: critical = renderKPIs + renderHighlights + renderCatChips + renderSkuList + renderVendedores; deferred = renderHero + renderLojaCards + renderPareto.
- **ecommerce.html** `renderAll()`: critical = renderWaterfall + renderKPIs + renderCanalTable + renderTopProdutos; deferred = renderHero + renderGeo + renderPayments + renderDowHeat + renderPareto + renderAds + renderAlerts.

### ⚠️ Teto de 50k linhas no `buscarTudo` → período longo (YTD/QTD/12m) trunca (25/06/2026)
`buscarTudo` (ecommerce.html) pagina até `MAX_PAGES=50 × 1000 = 50.000 linhas` e **para sem avisar**. O fetch detalhado de `vw_pedidos_full` para YTD (~167k pedidos) carregava só os primeiros 50k → **Receita Bruta R$4,65M em vez de R$17M (27%)**. QTD/12m idem (bug pré-existente, latente até o YTD passar de 50k pedidos em jun/26). Sintoma: chip de período "não funciona" / número muito baixo, **sem erro no console**.
- **Fix**: `carregar()` detecta `bigPeriod = diasP>50` (≈ >50k pedidos) e renderiza **100% pela MV agregada** (KPIs/waterfall/canais/hero/geo/pgto/produtos), **pulando o fetch detalhado**. `mvw_ecommerce_canal_dia` estendida **120→365d** (`sql/2026-06-25_mvw_ecommerce_canal_365d.sql`); as outras MVs (sku/geo/pgto) já cobriam todo o histórico. `renderHero` ganhou fallback pela canal_dia MV; `fetchSkuMV(de,ate,big)` usa teto 250k em período longo (sku_dia ~110k/ano). DOW/alertas/PA/unidades ficam off no longo (precisam de detalhe por pedido) + banner "visão agregada". `buscarTudo(tab,filtro,maxPagesOverride)` aceita teto custom.
- Régua: presets ≤50d (Hoje/7d/30d/MTD/Último Mês) seguem o caminho detalhado normal; QTD/YTD/12m caem no agregado.

### ⚠️ Armadilha do PostgREST: fetch de MV precisa `order` explícito

`buscarTudo()` injeta `&order=id.asc` por default se nenhuma order foi passada. **Materialized views não têm coluna `id`** → PostgREST devolve 400 silencioso e o KPI imediato nunca pinta. Sempre passar order explícito ao fetchar MV:

```js
async function fetchAgregadoMV(de, ate){
  return buscarTudo('mvw_lojas_dia',
    'select=*&data_pedido=gte.'+de+'&data_pedido=lte.'+ate+
    '&order=data_pedido.asc');  // ← sem isso, 400 silencioso
}
```

Bug detectado em produção 01/06/2026 — KPIs imediatos do lojas.html não apareciam.

---

## Dash Lojas Físicas (`lojas.html`) — Linx Microvix desde 01/06/2026

Renomeado de "Lojas v3" pra "Lojas Físicas" em 01/06/2026 junto com cutover Tiny→Linx.

Fonte: `vw_pedidos_full` (origem_conta=kwid). Histórico completo (out/24 → hoje) numa série única: pré-01/06 via Tiny (id_tiny numérico puro), pós-01/06 via Linx Microvix (`id_tiny LIKE 'linx_<uuid>'`, canal_nome_raw='Venda Loja'). Atacado/flecha excluído via `IGNORAR_LOJA`.

**Conceitos-chave para código:**
- Filtros persistentes na URL (`?de=...&ate=...&p=30d&lojas=...`)
- `lojaDisplay()` = identity (desde 23/04/2026). Nomes curtos são fonte da verdade na base. `LOJA_CORES` usa keys sem prefixo.
- Fotos vendedores: `vendedores/{primeiro-nome}.jpg` (lowercase, sem acento). `avatarHtml()` tenta `{primeiro-segundo}.jpg` → `{primeiro}.jpg` → iniciais.
- Metas: fetch de `metas_lojas` uma vez por sessão (`STATE.metasLoaded`). Sem meta = fallback gracioso.
- **Meta↔vendedor casa por NOME CRU** (`STATE.metasVend[p._vend][ano-mes]`). Canônico = **`pedidos.vendedor`** (nome de venda do Linx, pós-`VEND_ALIAS_LINX`). Metas e `kwid_vendedores` DEVEM usar esse nome — se cadastrar meta com nome completo/cadastro (ex: "Ana Julia Lima" vs venda "Júlia"), a meta **some silenciosamente**. Guard durável (06/07/2026): `seedVendedoresSemCadastro()` no drawer semeia como "novo" pré-preenchido (nome de venda + loja dominante de `STATE.pedidos`) quem está vendendo mas não tem `kwid_vendedores` ativo → drawer sempre oferece o nome de venda, impossível driftar. `NAO_VENDEDORES` (global) exclui contas não-vendedor. **Mesma pessoa, 2 rótulos Linx** (Linx renomeia ao longo do tempo, ex "Ana Julia"→"Júlia" em ~28/06): unificar via `VEND_ALIAS_LINX` no sync + `UPDATE pedidos SET vendedor` do histórico + refresh MVs lojas.
- **Cadastro de metas (botão verde topbar, 01/06)**: visível só pra whitelist `app_config.metas_editors_emails` (`carregarWhitelistMetas()` antes do `requireAuth`). Drawer escreve `metas_lojas` + `metas_vendedores` + CRUD `kwid_vendedores` via PostgREST com JWT (RLS valida whitelist). Whitelist é **fonte única** (UI + RLS). Policies usam `auth.jwt() ->> 'email'` (nunca `auth.users`). Drawer **fora do `<header>`** (backdrop-filter aprisiona `position:fixed`). Ler `app_config` com `&order=key.asc` (PK=`key`). DDL `sql/2026-06-01_metas_vendedores.sql`.
- Projeção do mês: média por DOW dos dias observados, fallback pra média diária. Ativa quando range inclui hoje.
- Charts: registro em `CHARTS`. Sparklines em `CHARTS.lojaSparklines[]`.
- Cross-filtering bidirecional: click vendedor ↔ click SKU.
- **Heatmap diário do vendedor (modal)**: clicar no NOME na tabela "Top vendedores" (`.vend-hm`, stopPropagation p/ não disparar o cross-filter da linha) abre `#hmcal-overlay` — calendário mensal (‹ › navega mês, default = mês do `ATE`) do vendedor. Fonte `mvw_lojas_vend_dia` (invariante ao período). 2 toggles: **métrica** receita↔vendas (qtd = `pedidos−cancelados`) e **vs Loja** (ranking dos vendedores da mesma loja no mês, na métrica atual, destacando o selecionado). Estado em `HM`/`HMCAL`; funções `hm*`. Modal é filho do `<body>` (backdrop-filter do header aprisiona `position:fixed`).
- Categorias excluídas: TECIDO, TROCA.
- **`Atacado Lojas` = entidade separada (20/07/2026)**: atacado vendido dentro das lojas (depósito Linx cod 7). Está no **`IGNORAR_LOJA`** de propósito → fora dos KPIs do topo, cards por loja, Top Produtos/Pareto, heatmap do vendedor e **atingimento de meta**. Aparece só em (a) card `.c-atacado` (`renderAtacado`) e (b) coluna "Atacado" do quadro de vendedores. Ambos saem de **`calcAtacado()` sobre `STATE.pedidosRaw` (PRÉ-`filtrarPedidos`)** — é o que permite isolar do varejo sem perder o número. Escopo = período do chip; **não** segue filtro de produto/categoria (os itens do atacado nem são buscados — o fetch de itens exclui `IGNORAR_LOJA`). Vendedor que só vendeu atacado é **semeado** no `agg` (senão sumiria da tabela, já que `agg` sai de `STATE.pedidos` filtrado).
  - **Comissão tem 2 réguas** (`COMISSAO`): varejo 2%/0,75% · **atacado 1,5%/0,75%**. O tier é destravado **só pelo varejo** (atacado não conta pra atingir meta, mas é pago no tier destravado). Tooltip quebra varejo × atacado.
  - ⚠️ **Inserir coluna no meio do quadro de vendedores exige mexer em 3 lugares**: o `<th>`, o template do `<tr>`, **e o CSS `nth-child(n+N)`** que esconde Meta→Comissão na visão mensal (era `n+9`, virou `n+10`) — além do `colspan` do estado vazio. Conferir com contagem: nº de `<th>` == `<td>` do template + `<td>` do `metaTd`.
  - ⚠️ **`mvw_lojas_vend_dia` precisa trazer `loja_nome` e filtrar `IGNORAR_LOJA`** — o consumo da "Meta hoje" não fazia isso, então o realizado do catch-up incluía atacado enquanto o `Atg.%` não, e as duas colunas discordavam (corrigido 20/07).

## ~~Dash Lojas Lynx~~ — REMOVIDO em 01/06/2026

`lojas-lynx.html` e o entry `'lojas-lynx'` em `auth.js` foram **deletados** após o cutover Tiny→Linx. O dash POC servia pra bater vendas físicas durante o rollout do Linx Microvix; depois do cutover, todas as vendas Linx vão direto pra `pedidos` (não mais pra staging) e o `lojas.html` ("Lojas Físicas") cobre tudo.

As tabelas `pedidos_linx_staging` + `itens_linx_staging` continuam no Supabase como histórico imutável do POC (3.609 ped maio/2026) — podem ser dropadas no futuro quando claramente irrelevantes. Detalhes do POC em memória `linx-microvix-poc-kwid` (arqueológica) e `cutover-lojas-tiny-linx-atacado-rotina-unica`.

## Dash Financeiro (`financeiro.html`)

Fonte única: tabela `contas_pagar` (só Fio e Trama).

**Conceitos-chave para código:**
- **Semana operacional sáb-sex (CRITICO)**: Fusion paga na segunda títulos de sáb/dom/seg. Fórmula: `offset = (weekday + 1) % 7; sábado = data - offset` (função `weekStart`). **Qualquer agrupamento por "semana" DEVE usar sábado como início** — semana ISO (segunda) dá resultado errado.
- **"Vencido operacional"** = `situacao='em_aberto' AND weekStart(vencimento) < weekStart(hoje)`.
- Aging BR: `A vencer | 1–7d | 8–30d | 31–60d | 60+d` (não 30-60-90 americano).
- Drill-down 3 níveis por categoria hierárquica. Rótulos em `CAT_LABELS` (mapa hardcoded — atualizar se surgir nível novo).
- Filtra fora `cancelada` E `cancelada_api` (função `processar()`).

## Dash Estoque (`estoque.html`)

**Conceitos-chave para código:**
- Query filtra `ativo=eq.true` — correções de grade feitas via `ativo=false` no Supabase (NÃO deletar).
- Whitelist fabricação própria (`SKU_FINALIZADOS`, 21 SKUs): `CLAFEL01, CLAF01, CLAJUSTE, CLTECH, CLMALHA, CLSJ01, CLMC01, CLOX01, CLDENIM01, CLSPIN01, CMBB, CMINDIANO, CMMC, CMEL01, CMLS01, CMPL01, CMGPD, SJPREMIUM, TNMC01, TNPV01, TNPVAJ`. **Manter sincronizado** em 3 lugares: `compras.html`, `estoque.html`, `fusion-sync/fusion_sync_producao.py`.
- **Pipeline de custo**: dash consome `produtos.custo_total`. Pipeline completo (RPC `recalcular_custos_sku`, `custos_sku`) em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).
- Aba **Insumos** é stub (não implementada).
- Render CLI disponível (`render login` se token expirar, `render jobs create` para disparar syncs).

## Dash Ecommerce (`ecommerce.html`)

- Fonte: `vw_pedidos_full` (excluindo lojas físicas e atacado). Detalhe agregado opcional via `mvw_ecommerce_canal_dia`.
- **P&L trata `devolvido` como venda bruta + devolução** (02/06/2026, Gross Sales − Returns = Net). ⚠️ Exceção à convenção compartilhada "filtrar `status NOT IN (cancelado,devolvido)`": só `cancelado` (não-venda) fica fora do P&L. `devolvido` entra na Receita Bruta E na linha Devoluções. Motivo: no Site Próprio a devolução vira **reversão total** (`status='devolvido'`, valor no `valor_devolucao`), não refund parcial como nos marketplaces — excluir devolvido inteiro escondia ~90% da devolução do site (mostrava R$2k de R$21k). `calcPnL` pula só `p._cancelado`; `filtrarPedidos` mantém devolvido em `ativos` mas com `_canc=true` (gráficos/rankings operacionais seguem excluindo). Linha Devoluções soma `valor_devolucao + valor_chargeback`. A MV `mvw_ecommerce_canal_dia` espelha (FILTER `status<>'cancelado'`; `cancelados` conta só cancelado). DDL: `sql/2026-06-02_mvw_ecommerce_devolvido.sql` + `_vw_pedidos_full_chargeback.sql`.
- **Devolução real do Site Próprio = Troquecommerce, não Shopify** (02/06/2026): o site gere trocas/devoluções no Troque (RMA); ~64% são TROCAS (vale-crédito, sem dinheiro de volta) → invisíveis no refund Shopify. `fetchTroqueSite()` lê `vw_devolucao_site_dia`; `renderAlerts` mostra **taxa operacional** (incl. troca, ~11-14%) vs **perda de caixa** (estorno, ~5%). Refund monetário do Shopify (`valor_devolucao`) ≈ `refund_value` do Troque — segue sendo o que entra no P&L (troca não é perda de receita). Tabela `devolucoes_site` via `fusion_sync_troque.py`.
- **Custos por canal**: tabela `CANAL_CUSTO` hardcoded. Fonte da verdade: [../CUSTOS_POR_CANAL.md](../CUSTOS_POR_CANAL.md).
- **Coluna Afiliados (02/07/2026)**: linha própria no P&L (`pedidos.comissao_afiliado`), separada da Comissão. Fonte por canal: TikTok=`affiliate_commission_amount` do statement (extraído do `fee_amount` e **subtraído de fee_canal** — senão double-count), Shopee=`order_ams_commission_fee` do escrow, ML=billing "Tarifa de programa de afiliados" (**PENDENTE**, fase 4). Só programa da plataforma (Leo confirmou: sem cachê/permuta fora). Toca ~19 pontos no HTML (espelha o padrão da coluna `impostos`) + `afiliado` nas MVs `canal_dia`/`canal_mes` + `comissao_afiliado` no `SEL_PED`. `vw_pnl_bu_mensal` (financeiro) soma afiliado no custo variável. Magnitude: TikTok ~R$57k/mês (estava escondido na Comissão), Shopee ~R$9k/mês (era invisível). Plano/armadilhas da API de billing ML em [../TODO_AFILIADOS.md](../TODO_AFILIADOS.md).
- Margem líquida = receita − (receita × custo_canal%) − Σ(qty × `produtos.custo_total`).
- **CMV (02/06/2026)**: real (item × `produtos.custo_total`; p/ fab. própria = `custos_sku.cmv_total_peca`, custo dinâmico WAC dos costureiros) pros meses dentro de `janelaItens()` (período selecionado, teto `CMV_DIAS_REAIS=130`d — cobre abr/mai/jun); meses mais antigos + first-paint usam **proporção REAL por canal** `cmvPct()`/`CMV_PCT_CANAL` (média abr+mai: ML 43% Shopee 40% TikTok 47% Site 29% Shein 38%), que substituiu o placeholder fixo de 45%. `calcPnL` particiona por `data_pedido`>=`janelaItens(DE)` (sem double-count). Atualizar `CMV_PCT_CANAL` periodicamente.
- **Camada de estimativa — o MTD parou de se lisonjear (Fase 3, 14/07/2026)**. Antes, pedido que ainda não liquidou tinha custo **zero**, então a margem do mês corrente era a melhor que ela jamais seria (TikTok: **85%** da receita de julho sem `fee_canal`; Site: 62%). Pior: a **mesma** comissão aparecia com valores diferentes em 4 telas — o fallback `custoPct` só existia em `calcPnL` (waterfall), não em `calcPnLFromMV`, `_canalRowsArr` nem na lista de produtos (TikTok jul: R$19,6k no waterfall vs R$3,2k na tabela/produtos).
  - **Fonte única em SQL** (`sql/2026-07-14_camada_estimativa.sql`), **sem rebuild de MV**: `vw_ecom_taxas_estim` (taxas) + `mvw_curva_devolucao` (maturação) + `vw_ecom_canal_dia_est` / `vw_ecom_sku_dia_est` (= a MV + colunas `*_est`). O dash lê as colunas prontas; o caminho por pedido (`calcPnL`) aplica a **mesma** regra com as **mesmas** taxas → os 4 números batem **ao centavo** (validado: R$0,00).
  - ⚠️ **NÃO usar `vw_sim_canal_taxas` pra estimar.** Ela divide o fee pela receita de **todos** os pedidos, inclusive os imaturos (fee=0), então vem **diluída**: TikTok 5,07% quando a taxa real sobre liquidados é **7,88%**. Estimar com ela reproduz exatamente o viés otimista que a camada existe pra matar. `vw_ecom_taxas_estim` usa denominador = receita dos pedidos **liquidados** (`fee>0`).
  - **Devolução usa CURVA, não taxa fixa** (`mvw_curva_devolucao`, coortes fechadas 180-90d): aplicar "ML devolve 10,5%" sobre o MTD super-provisiona — o pedido de ontem mal começou a janela. Fórmula **Bornhuetter-Ferguson**: `provisão = (1 − fator(dias)) × receita × taxa_hist`. Fator 1 (maduro) → provisão 0; fator 0 (venda de hoje) → provisão cheia. Sem divisão por zero, e o real substitui a estimativa sozinho. Curvas: ML 70%@7d·99%@30d · Shopee 74%@7d·100%@30d · TikTok 43%@7d·96%@30d · Site 9%@7d·81%@30d (RMA lento).
  - ⚠️ **`fee_canal` NULL ≠ 0** (armadilha que nos pegou em 14/07). **NULL = não liquidou** (não há statement) → estima. **0 = liquidou e a comissão líquida deu zero** → nada a estimar. No TikTok o "0" é comum: pedido devolvido por inteiro (a plataforma **estorna** a comissão) e pedido em que o afiliado consome o fee inteiro — ~7.200 pedidos. Testar `fee > 0` tratava os dois como iguais e cobrava comissão de quem já tinha liquidado. As views usam `fee_canal IS NULL`; o JS testa `p.fee_canal !== null` (⚠️ `parseFloat(null||0)` = 0, então não dá pra confiar no valor numérico). E `backfill_statement_tiktok.py` grava `fee_canal = 0` **explícito** quando há statement. ⚠️ **`comissao_afiliado` e `frete_ml_seller` têm DEFAULT 0** — nunca são NULL, então **não servem** como sinal de "liquidou".
  - **Regra de ouro:** estimar só o **buraco**, nunca por cima de um valor real (liquidou → usa o real).
  - **Rotulado na UI (A6)**: barra hachurada + chip "est." no waterfall, chip na tabela de canal, aviso com o total estimado. Uma boa estimativa é perigosa quando para de parecer estimativa.
  - **Magnitude (jul/26):** R$127,9k de custo que o dash não mostrava = **8,3 pontos** de margem inflada. Meses fechados: `*_est` ≈ 0 pra ML/Shopee (liquidam no ato) → zero regressão (A9).
- **Real (API) vs estimado/proporcional no P&L** — régua completa em [../CUSTOS_POR_CANAL.md](../CUSTOS_POR_CANAL.md#real-api-vs-estimadoproporcional-no-pl-auditoria-08062026). Resumo: **banco só guarda valor real da API** (fee_canal/frete_ml_seller/valor_devolucao/valor_chargeback/devolucoes_item/ads_metrics; sem dado = 0/null, nada estimado gravado). **Reais**: receita, devolução (order + por produto), comissão madura, frete ML/TikTok/Shopee, ads ML+Shopee. **Estimados/proporcionais (fallback de tela)**: CMV de meses >130d (`cmvPct`), comissão não-maturada (`custoPct`), frete Site (usa frete do cliente como proxy), ads Meta/Google/TikTok (R$0, ausente). Shein tudo estimado até API direta ([../TODO_SHEIN_API.md](../TODO_SHEIN_API.md)).

## Dash Diretoria (`diretoria.html`)

- Visão executiva consolidada **agrupada por CANAL** (não por empresa/CNPJ — reescrito 01/06/2026). 4 grandes grupos → subgrupos.
- Fonte: `mvw_diretoria_dia` (todas as origens). 1 fetch cobre [período anterior + atual]; split client-side por `data_pedido` pra calcular **Δ% vs período anterior equivalente** (mesma duração imediatamente antes de DE).
- **Régua Net Sales (08/06/2026 — alinhada ao ecommerce.html)**: a MV e o dash usam `Receita Líquida = Faturamento Bruto − Devoluções` como métrica-âncora. `receita_bruta` inclui `devolvido` (`FILTER status<>'cancelado'`, idêntico a `mvw_ecommerce_canal_dia`); coluna `devolucoes` = `valor_devolucao + valor_chargeback`; `cancelados` conta só cancelado. **Não usa `valor_liquido`** — está em enriquecimento inconsistente (== valor_bruto em parte das rows; gap agregado não bate com fee nem devolução) e comissão/frete são custo, não dedução de receita. KPIs: Bruto · Devoluções (R$+% do bruto) · **Líquido (âncora, verde)** · Pedidos · TM líq · Fat/Dia líq. Tabela e charts (mensal/mix/barras) usam líquido; só a coluna "Bruto" e a seção Projeção 2026 ficam em bruto (meta da planilha é bruta). DDL: `sql/2026-06-08_mvw_diretoria_regua_net.sql`. Helpers JS: `REC`/`DEV`/`liqOf`; cache bumped `v3`→`v4`.
  - **Motivo / por que importava**: antes a diretoria saía da MESMA tabela `pedidos` que lojas/ecommerce (não há separação por CNPJ — `origem_conta` é só rótulo), mas com régua `NOT IN (cancelado,devolvido)` → excluía o devolvido inteiro, mostrava o ecommerce ~R$88k menor (120d) e escondia ~R$737k de devolução parcial. Pós-fix: Σ por canal da diretoria == `mvw_ecommerce_canal_dia` **ao centavo** (validado 08/06). Gap residual só vs `mvw_lojas_dia` (~R$1.430/365d): o lojas ainda exclui devolvido e KWID não tem `valor_devolucao` — imaterial, alinhar é escopo à parte.
  - **Taxa de devolução por canal** é o ganho de qualidade real (KPI de saúde de moda). Medida por **data do pedido** (coorte) → meses recentes maturando (subestima). Nota disso no rodapé da tabela consolidada.
- **Fase 1 do redesign (08/06/2026)**: (a) **KPIs do topo** = Receita Bruta · Receita Líquida (âncora, devolução no sub, não mais KPI próprio) · **Previsão [mês]** · Pedidos · Ticket · Fat/Dia. (b) **Cards por grupo** = faturamento líquido em destaque + Pedidos/Ticket/Fat-dia (`.origem-metrics`) + **Prev. [mês]**; sem devolução nem "% do líquido". (c) **Atacado ganhou container próprio** (barras `atacado-bars` Flecha/Atacado WhatsApp + diário `chart-atacado`), além do card e tabela. (d) **Previsão de fechamento do mês** (`preverMesPorGrupo`) = média por **dia-da-semana** dos dias observados × dias do mês (mesmo método do lojas.html; fallback média diária). Independe do filtro (sempre mês corrente). ⚠️ Reflete ritmo real — pode parecer alta em meses fortes (jun/26: ~R$6,4M vs ~R$4,9M de maio por causa do Dia dos Namorados).
- **Fase 2 (pendente) — Margem de Contribuição por canal**: cascata Receita Líquida − **CMV** − despesas variáveis (comissão `fee_canal` + frete + ads + devolução) por canal. **NÃO reconstruir** a lógica do P&L aqui — o `ecommerce.html` já calcula isso e está em evolução; o caminho é extrair uma **MV canônica de margem por canal/dia** consumida pelos dois dashes (fonte única, evita divergência). Bloqueios: (1) estabilizar P&L ecommerce; (2) lojas/atacado não têm os variáveis na base (comissão de vendedores + Google Ads não existem — só ML+Shopee ads via `ads_metrics`); (3) despesas fixas (ocupação/sistemas) virão depois, fora da MC variável. Decisão 08/06: fase 1 (receita) agora, MC depois via fonte única.
- **Classificação canal-first** (`classificarGrupo(row)` — toda row cai em 1 grupo, Σ grupos == total):
  - **Marketplaces**: `classificarCanal(canal_nome_raw)` ∈ {Mercado Livre, Shopee, Shein, TikTok Shop, Magalu}. Classificador por substring (`includes`) cobre as 15+ variantes históricas (`ML Fio e Trama`, `ML Confecções`, `Mercado Livre FIO`...). ⚠️ O `CANAL_MAP` exato-match antigo perdia ~R$13M de ML — não voltar pra ele.
  - **E-commerce (Site)**: canal = Site Próprio/web (ou fallback `origem_conta='shopify'`).
  - **Lojas Físicas**: `origem_conta='kwid'` via `loja_nome` normalizado (NÃO `canal_nome_raw`), exceto Atacado WhatsApp.
  - **Atacado** (4º grupo, decisão 01/06/2026): `flecha` + KWID `loja_nome='Atacado WhatsApp'`.
- Validar mudança no classificador: Σ dos 4 grupos deve bater com soma de todas as origens (`mvw_diretoria_dia`). 12m em 01/06: total R$46,3M = Mkt 60,5% + Lojas 29,8% + E-com 7,5% + Atacado 2,1%.
- **Gráfico "Evolução mensal por canal" = SEMPRE últimos 12 meses** (independente do filtro); o resto (KPIs/cards/mix/barras/tabela) segue o período. Por isso o fetch cobre a união `[12m fixos + período anterior]` e fatia client-side (`cur`/`prev`/`mensalRows`).
- **Mix (doughnut)** mostra % em cada fatia via `chartjs-plugin-datalabels` (registrado **per-chart** em `plugins:[ChartDataLabels]`, não global — senão poluiria barras/linhas); esconde fatias <3%.
- ⚠️ **Fetch DEVE paginar** (`apiAll()`, não `api()`): a MV tem ~4.4k linhas em 12m e o PostgREST corta em 1000. Sem paginar, `order=data_pedido.asc` trazia só as 1000 mais antigas e o período atual zerava (regressão 01/06, corrigida no mesmo dia). Ordem de paginação = chave única da MV (`data_pedido,origem_conta,canal_nome_raw,loja_nome`) pra offset exato. Ver [[feedback-postgrest-pagination]].
- **Chip "Ano (YTD)"** (`setPeriodoYTD`): 1º jan do ano corrente → hoje.
- **Seção "Projeção de Receita 2026"** (`renderProjecao`, sempre ano calendário — **independe do filtro**, como o gráfico mensal): 4 KPIs (realizado YTD c/ % da meta YTD · forecast fechamento · meta oficial · atingimento) + gráfico Jan-Dez de barras empilhadas (realizado + projeção) com linha de meta.
  - **Forecast = sazonal**: ritmo diário do YTD 2026 (`ytd/dias_decorridos`) × índice de sazonalidade de 2025 por mês (`daily25[m]/baseline`). Mês corrente = realizado + projeção dos dias restantes; futuros = projeção cheia. ⚠️ Como a MV só guarda 365d, a sazonalidade usa **2025-06→12** (não o ano anterior inteiro) — meses sem base usam índice 1.
  - **Meta** vem de `projecao_faturamento` (Cockpit; `tipo=projetado`, `versao=1`, planilha `PROJEÇÃO FUSION 2026.xlsx`), somada por mês entre os macro_canais. Carregada 1× em `META_ROWS`. Validação 01/06: forecast R$51,4M vs meta R$40,9M (126%); realizado YTD = 118% da meta YTD.

## Dash Simulador (`simulador.html`)

- Calculadora de margem por SKU+canal+preço, curva ótima de ads, antes/depois (snapshot+manual), cenários salvos por user (RLS).
- Detalhes de fórmula, fontes e limitações em [SIMULADOR.md](SIMULADOR.md).
- Depende de tabelas `canal_custos_faixa`, `simulacao_cenarios`, `produtos_snapshot`, `produto_evento`, `ads_curva_otima` e views `vw_taxa_devolucao_*`/`vw_frete_medio_*` (criadas em `sql/2026-05-01_*.sql`).
- Crons que alimentam: `fusion-sync-snapshot` (08h BRT) e `fusion-sync-curva-ads` (09h BRT) — ver [../fusion-sync/CLAUDE.md](../fusion-sync/CLAUDE.md).

## Dash Projetos (`projetos.html`) — gestão de projetos estratégicos (iniciado 11/05/2026)

Sistema de PM completo pra Aquisição Facção Paraná + Fábrica SAS (ex-"Fábrica Paraguay", retipada 26/05/2026 — Santo Antônio do Sudoeste/PR; v1 escopo "só interno Fusion"). Schema em `sql/2026-05-11_projetos_v1.sql` (12 tabelas + 4 triggers + 2 views) + seed em `sql/2026-05-11_projetos_seed.sql`.

**Tabelas**: `pessoas`, `projetos`, `projeto_pessoas`, `projeto_marcos`, `projeto_tarefas`, `projeto_decisoes`, `projeto_riscos`, `projeto_paginas`, `projeto_comentarios`, `projeto_anexos`, `projeto_atividades` (log append-only por triggers), `projeto_notificacoes`. Views: `vw_projeto_resumo`, `vw_minhas_tarefas`.

**Conceitos-chave**:
- Externos (advogados/contadores Paraguay) entram só em `pessoas` sem `user_id` — sem login, info trafega via diretoria
- Banner colorido do projeto + seletor (dropdown) no topo; estado salvo em `localStorage` (`proj_atual`) e refletido na URL (`?p=<uuid>`)
- Kanban drag-and-drop nativo (HTML5 dragstart/drop) — sem libs. Move status via PATCH em `projeto_tarefas`
- **Tarefas têm múltiplos responsáveis** (28/05/2026): `projeto_tarefas.atribuidos_a uuid[]` (substituiu `atribuida_a` single). Drawer = checkboxes (`#f-resp .chk-list`); filtro responsável usa `.includes()`; `vw_minhas_tarefas` faz `JOIN pessoas ON id = ANY(atribuidos_a)`; trigger de notificação itera só os ids novos. Filtro PostgREST: `atribuidos_a=cs.{<uuid>}`. DDL em `sql/2026-05-28_tarefas_multi_responsavel.sql`
- `vw_minhas_tarefas` filtra automaticamente por `auth.uid()` via join em `pessoas.user_id` — usar pra aba "Minhas"
- Triggers SQL: toda mudança em tarefa/decisão/risco/marco vira linha em `projeto_atividades`. Atribuição de tarefa → INSERT em `projeto_notificacoes` (só se a pessoa tem user_id)
- Drawer universal: 3 templates (tarefa/pessoa/marco) — IDs `f-titulo`/`f-status`/`f-descricao` reutilizados (drawer renderiza só 1 por vez)
- Sprint 1 entregou Visão/Tarefas/Pessoas/Marcos. **Sprint 2 completo (28/05/2026)**: abas Decisões + Riscos (lista + drawer + pills); **Comentários universais** (seção no drawer ao editar tarefa/marco/decisão/risco — `projeto_comentarios` por entidade_tipo+entidade_id, autor=`pessoaMe.id`); **sino de Notificações** no header (`projeto_notificacoes` filtrado por `destinatario_id=auth.uid()`, badge de não-lidas, dropdown que marca lida + navega à entidade, "marcar todas"). **Sprint 3 parcial (28/05/2026): aba Wiki** (`projeto_paginas` — sidebar de páginas + view/edit, editor markdown com `marked`+`DOMPurify` via CDN, CRUD; hierarquia `parent_id` ainda não usada — lista flat). **Sprint 3 completo (29/05/2026): aba Anexos** (`projeto_anexos` + bucket **privado** `projetos-anexos`, limite 50MB). Upload via Storage REST (`POST /storage/v1/object/{bucket}/{path}` com JWT do user, path=`{projeto_id}/{ts}-{nome}`), download por signed URL (`/object/sign`, expira 120s), exclusão remove objeto + row. Policies em `storage.objects` (`anexos_auth_{select,insert,delete}` pra `authenticated`). Sprint 4 (pendente): busca Cmd+K + export PDF + mobile polish
- **6 abas hoje**: visao/tarefas/pessoas/marcos/decisoes/riscos. `projeto_decisoes` (titulo/contexto/alternativas/decisao/justificativa/responsavel_id/participantes[]/data_decisao/impacto/status) e `projeto_riscos` (titulo/descricao/probabilidade/impacto/mitigacao/responsavel_id/status). Drawer universal agora cobre 5 kinds: tarefa/pessoa/marco/decisao/risco (switch em `drawerBodyHTML`/`submitDrawer`/`excluirDrawer`)

**Roadmap completo** em `~/.claude/plans/robust-chasing-parnas.md`.

## Dash Max Chat — Admin (`max-chat-admin.html`) — restrito a leonardo@usefusion.com.br

Painel de qualidade do Max Chat com **ações executáveis** (write — não só leitura). Criado 02/05/2026.

**Acesso restrito por email** — convenção nova:
```js
'max-chat-admin': { ..., restritoPara: ['leonardo@usefusion.com.br'] }
```
- `index.html` filtra cards por `meta.restritoPara` (não renderiza se email não bate)
- `max-chat-admin.html` valida `ALLOWED_EMAILS` no init (redirect se outro user com role admin acessar URL direta)
- Defesa em profundidade: 3 camadas (`user_roles.dashes` + `restritoPara` + `ALLOWED_EMAILS`)

**Conteúdo do painel** (6 cards):
1. KPIs do mês: 👍/👎, cobertura feedback, falhas, custo
2. 👎 Respostas mal avaliadas (motivo escrito pelo user)
3. 🔴 Falhas detectadas automaticamente (sem precisar 👎)
4. 💰 Perguntas frequentes sem snapshot (candidatas a otimizar)
5. 📊 Aprovação por categoria (% mês corrente)
6. 📋 Sugestões registradas (com SHA clicável quando implementada)

**Ações executáveis** (chamam endpoints `https://max-chat-2vs0.onrender.com/api/max-chat/admin/*`):
- 🚀 **Disparar cron de sugestões agora** — POST `/admin/disparar-cron-sugestoes` triggera o cron `max-chat-apply-sugestoes` via Render API. Polling de status (até 4min). Alert com highlights dos logs ao final
- 🔄 Repopular snapshots agora — força `snapshots.py` em produção
- ⚙️ Recarregar config — POST `/admin/reload`, força backend re-ler `categorias.yaml`
- + Nova sugestão — abre dialog (tipo, pergunta, proposta, prioridade)
- Por linha de sugestão pendente: **✓ aprovar** (libera pro cron processar) / **✗ rejeitar**
- Por linha de falha/down: **Tratar** (registra em `max_chat_falhas_tratadas`, esconde do painel)
- Por linha de candidata sem snapshot: **Sugerir snapshot** (pré-preenche dialog com a pergunta)

**Endpoints chamados** (todos `auth_required(admin_only=True)` no max-chat backend):
- `GET  /admin/qualidade` — payload completo (resumo + downs + ups + falhas + sem_snap + aprovação)
- `GET  /admin/sugestoes` — lista sugestões registradas
- `POST /admin/sugestao` — cria nova
- `POST /admin/sugestoes/<id>` — muda status (aprovada/implementada/rejeitada/pendente)
- `POST /admin/falhas/marcar-tratada` — registra `max_chat_falhas_tratadas`
- `POST /admin/disparar-cron-sugestoes` — triggera cron via Render API (precisa `RENDER_API_TOKEN` env no backend)
- `GET  /admin/cron-job/<job_id>` — polling de status + logs
- `POST /admin/repopular-snapshots` — subprocess `snapshots.py`

**Workflow completo de melhoria contínua:**
```
You no painel → registra sugestão (pendente)
          → revisa → ✓ aprovar (aprovada)
          → ⏰ segunda 10h BRT (ou clica "Disparar agora")
          → cron Render lê aprovadas + valida SQL + git push em main
          → Render auto-deploya max-chat web
          → painel mostra SHA clicável (implementada)
```

## Smoke checks pós-deploy

Rodar após qualquer push em fusion-dash. **A skill [`fusion-sanity-check`](../.claude/skills/fusion-sanity-check/SKILL.md) automatiza isso.**

```bash
BASE="https://fusion-dash.onrender.com"

# 1. Cada dash CHEIO retorna 200 + HTML não-trivial (>20KB)
# ⚠️ NÃO incluir aqui os wrappers finos de app React (financeiro/crm/compras-react/produtos:
# ~2-3KB por design, são iframe + gate) nem o portal index.html (~10KB) — a régua de 20KB
# é só pra dash vanilla. `projetos` saiu do catálogo em 10/07/2026.
for d in compras lojas ecommerce diretoria estoque; do
  size=$(curl -s -o /dev/null -w "%{size_download}" "$BASE/$d.html")
  echo "$d.html: ${size}B" && [ "$size" -gt 20000 ] || echo "  ⚠️ tamanho suspeito"
done

# 1b. Wrappers finos + portal: checar 200 + gate + destino do iframe (não tamanho)
for d in financeiro crm compras-react produtos; do
  W=$(curl -s "$BASE/$d.html")
  echo "$W" | grep -q "requireAuth(" && echo "✅ $d.html com auth gate" || echo "🔴 $d.html sem requireAuth"
  echo "$W" | grep -q "<iframe" && echo "✅ $d.html embute o app" || echo "🔴 $d.html sem iframe"
done
curl -s -o /dev/null -w "index.html HTTP %{http_code}\n" "$BASE/index.html"

# 2. compras.html — invariantes do refactor Phase 2 (devem aparecer)
HTML=$(curl -s "$BASE/compras.html")
echo "$HTML" | grep -q "'Em Produção'" && echo "✅ status novo presente" || echo "🔴 status novo ausente"
echo "$HTML" | grep -q "vw_insumo_saldo_local" && echo "✅ view insumo carregada" || echo "🔴 view insumo ausente"
echo "$HTML" | grep -q "renderReguaPagamentos" && echo "✅ régua pagamentos OK" || echo "🔴 régua ausente"
echo "$HTML" | grep -q "tbody-regua-pagamentos" && echo "✅ tbody régua único" || echo "🔴 tbody régua ausente"

# 3. compras.html — armadilhas conhecidas (NÃO devem aparecer)
echo "$HTML" | grep -q "'Produzindo'" && echo "🔴 status antigo 'Produzindo' aparece" || echo "✅ sem status antigo"
echo "$HTML" | grep -q "'cancelada'" && echo "🔴 status antigo 'cancelada' aparece (em ordens_producao)" || echo "✅ sem cancelada bare"
echo "$HTML" | grep -cE '<tbody id="tbody-pagamentos"' | grep -qE '^[01]$' && echo "✅ tbody-pagamentos único ou ausente" || echo "🔴 tbody-pagamentos duplicado"
# Detecta </script> literal dentro de string JS (literal `'</script>'` quebra o parser HTML)
echo "$HTML" | grep -qE "'</script>'" && echo "🔴 </script> literal em string JS" || echo "✅ sem </script> literal"

# 4. jsPDF carregado (necessário pra Sprint 7 do refactor)
echo "$HTML" | grep -q "jspdf" && echo "✅ jsPDF presente" || echo "🔴 jsPDF ausente"

# 5. simulador.html — invariantes (4 abas + chamadas pra views + sem armadilhas)
HTML=$(curl -s "$BASE/simulador.html")
echo "$HTML" | grep -q 'id="tab-calc"' && echo "✅ simulador aba calc" || echo "🔴 aba calc ausente"
echo "$HTML" | grep -q 'id="tab-curva"' && echo "✅ simulador aba curva" || echo "🔴 aba curva ausente"
echo "$HTML" | grep -q 'id="tab-antesdepois"' && echo "✅ simulador aba antesdepois" || echo "🔴 aba antesdepois ausente"
echo "$HTML" | grep -q 'id="tab-cenarios"' && echo "✅ simulador aba cenarios" || echo "🔴 aba cenarios ausente"
echo "$HTML" | grep -q 'canal_custos_faixa' && echo "✅ simulador lê canal_custos_faixa" || echo "🔴 canal_custos_faixa ausente"
echo "$HTML" | grep -q 'ads_curva_otima' && echo "✅ simulador lê ads_curva_otima" || echo "🔴 ads_curva_otima ausente"
echo "$HTML" | grep -qE "'</script>'" && echo "🔴 simulador </script> literal" || echo "✅ simulador sem </script> literal"

# 6. projetos.html — invariantes Sprint 1
HTML=$(curl -s "$BASE/projetos.html")
echo "$HTML" | grep -q 'id="tab-visao"' && echo "✅ projetos aba visao" || echo "🔴 aba visao ausente"
echo "$HTML" | grep -q 'id="tab-tarefas"' && echo "✅ projetos aba tarefas" || echo "🔴 aba tarefas ausente"
echo "$HTML" | grep -q 'id="tab-pessoas"' && echo "✅ projetos aba pessoas" || echo "🔴 aba pessoas ausente"
echo "$HTML" | grep -q 'id="tab-marcos"' && echo "✅ projetos aba marcos" || echo "🔴 aba marcos ausente"
echo "$HTML" | grep -q "fusionAuth.requireAuth('projetos')" && echo "✅ projetos auth gate" || echo "🔴 auth gate ausente"
echo "$HTML" | grep -q 'vw_minhas_tarefas' && echo "✅ projetos lê vw_minhas_tarefas" || echo "🔴 view minhas tarefas ausente"
echo "$HTML" | grep -qE "'</script>'" && echo "🔴 projetos </script> literal" || echo "✅ projetos sem </script> literal"
```

**Invariantes cross-arquivo críticos**:
- Status names (`Em Produção`, `Cancelado`, `Devolvido Fornecedor`) devem bater com o que `fusion_sync_producao.py` filtra E com o que `max-chat/backend/prompts/schema_compras_producao.md` documenta.
- IDs HTML únicos no documento (especialmente `tbody-*`, `kpis-*`).
