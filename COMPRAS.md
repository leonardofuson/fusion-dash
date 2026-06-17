# COMPRAS — sistema de input OC/OP + MRP

> Documento canônico do domínio **Compras/Produção**. Segue o padrão [../DASH_DOC_TEMPLATE.md](../DASH_DOC_TEMPLATE.md).
> **Único dash que ESCREVE no banco** (OC de tecido/aviamento + OP de produção). Schema em [../SCHEMA.md](../SCHEMA.md).
> Lógica preditiva (MRP, cobertura, custo) em [../fusion-sync/MRP.md](../fusion-sync/MRP.md). Convenções de UI (Chart.js, JWT, mobile) em [CLAUDE.md](CLAUDE.md).

## Metadata

| Campo | Valor |
|---|---|
| **Domínio** | Compras (OC tecido) + Produção (OP costureiros) + MRP |
| **Status** | Produção (refactor Phase 2/3 concluído abr/mai 2026) |
| **Owner** | Leo |
| **Última atualização** | 2026-05-28 |
| **Repos envolvidos** | `fusion-dash` (`compras.html`, input) + `fusion-sync` (`fusion_sync_producao.py`, MRP + custo) |
| **Service Render (MRP)** | `fusion-sync-producao` (cron `0 9 * * *` = 06h BRT) |
| **Dash URL** | `bi.usefusion.com.br/compras.html` (gate `dashes[]='compras'`) |
| **Arquivos que rodam** | `compras.html` (~6000 linhas — input do usuário) + `fusion_sync_producao.py` (MRP/custo, cron diário) |

---

## 1. Visão geral — por quê

O dash Compras é onde o time **registra** ordens de compra de tecido e ordens de produção (envio pra costureiro), e onde o **MRP** sugere o que produzir. Diferente de todos os outros dashes (que só leem), este **escreve** no banco e é o coração do fluxo de produção: tecido entra → vira OP no costureiro → volta como produto → alimenta o custo (CMV) que o ecommerce consome.

## 2. Quadro resumo — de onde vêm os dados

| Origem | Como entra | Destino | Frequência |
|---|---|---|---|
| **Input manual** (usuário no dash) | Forms/drawer em `compras.html` (Nova OP, Nova OC, entregas, cadastros) | `ordens_producao`, `producao_entregas`, `movimentacao_insumos`, `estoque_insumos`, `costureiros` | sob demanda |
| **MRP (sugestões)** | `fusion_sync_producao.py` calcula cobertura/ponto de reposição | `planejamento_producao` (lido pela aba Planejamento) | cron diário 06h BRT |
| **Custo (CMV)** | RPC `recalcular_custos_sku()` (cron passo 8 + botão) | `custos_sku` → `produtos.custo_total` | cron diário + manual |

## 3. Lineage

```
Usuário (dash) ──► compras.html ──► ordens_producao / producao_entregas ──┐
                                    movimentacao_insumos / estoque_insumos │
                                    costureiros                            │
                                                                           ├─► recalcular_custos_sku()
fusion_sync_producao.py (cron 06h):                                        │   (WAC v6) ──► custos_sku
  vendas 90d (vw_pedidos_completo) + estoque + em_producao                 │        └─► produtos.custo_total
  ──► planejamento_producao (sugestões) ──► aba Planejamento               │              └─► dash ecommerce
                                                                           │
movimentacao_insumos (event log) ──► trigger fn_atualizar_estoque_insumo ──┘──► estoque_insumos.quantidade_atual
                                  └─► vw_insumo_saldo_local (saldo por localização)
```

## 4. ⭐ Conceitos centrais (semântica)

### Status de OP (`ordens_producao.status`) — 4 valores válidos
| Status | Significado |
|---|---|
| `Em Produção` | Tecido na facção (inclui entregas parciais — trigger NÃO muda mais pra `parcial` desde 11/05) |
| `Entregue` | Produto no CD (`data_entrega_real` + `qtde_pecas_entregues`). **CHECK `chk_entregue_tem_data`** garante no DB |
| `Devolvido Fornecedor` | Peças com defeito devolvidas pra remanufatura |
| `Cancelado` | Anulação definitiva |
> Valores legados `Produzindo`/`cancelada`/`parcial`/`concluida` **não existem mais** (renomeados 26/04 + 11/05). `No CD`/`Costureiro - Estocado` são **localizações**, não status.

### Movimentação de tecido — event-sourced (desde 26/04)
`estoque_insumos.quantidade_atual` é mantido por **trigger** em `movimentacao_insumos`. **NUNCA fazer PATCH direto** em `quantidade_atual` — sempre via mov (preserva audit trail). 6 tipos canônicos de `tipo_mov`:

| `tipo_mov` | Quando | Sinal | Localização |
|---|---|---|---|
| `compra` | Cadastro de insumo / OC (auto desde 28/04) | + | "Local de estoque" do form (default CD FUSION) |
| `saldo_inicial` | Backfill / migração | + | local atual |
| `envio_costureiro` | Criar OP ou Transferir (par -origem/+destino) | par ± | conforme |
| `consumo_op` | Entrega parcial/total (`qty × consumo_por_peca`; usa `COALESCE(quantidade_tecido_usada, metros_kg)`) | − | costureiro |
| `retorno_cd` | Cancelar/excluir OP (espelha `envio_costureiro`) ou Transferir→CD | par invertido | origem real |
| `ajuste_compra` | Editar "Total Comprado" no drawer Insumo | ± delta | default |

- **`nf_remessa`** (28/04): NF Fusion Remessa quando tecido sai do CD pro costureiro. Persiste no par de movs; obrigatória nesse fluxo.
- **View `vw_insumo_saldo_local`**: `SUM(quantidade) GROUP BY insumo_id, localizacao`.

## 5. Rotina de atualização

| Gatilho | Quando | O que faz |
|---|---|---|
| **Input no dash** | sob demanda | INSERT/UPDATE/DELETE nas tabelas (forms drawer) |
| **`fusion-sync-producao`** (cron) | diário **06h BRT** (`0 9 * * *`) | recalcula MRP → `planejamento_producao`; passo 8 roda `recalcular_custos_sku()` |
| **Botão "Recalcular"** (aba Custos) | sob demanda | força `recalcular_custos_sku()` |

**Parâmetros MRP** (em `fusion_sync_producao.py`): lead produção 45d · lead tecido 5d · estoque mínimo 60d de venda · vendas referência 90d. Fórmula completa em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).

## 6. Schema — tabelas que ESCREVE

| Tabela | Operações |
|---|---|
| `ordens_producao` | INSERT (Planejamento/Nova OP), UPDATE (status/edição), DELETE (com inversão de movs) |
| `producao_entregas` | INSERT (entrega parcial/total), UPDATE (corrigir), DELETE (cancelar) |
| `movimentacao_insumos` | INSERT (todos os fluxos), DELETE (só ao excluir insumo) |
| `estoque_insumos` | INSERT (nova compra), PATCH (metadados — saldo NÃO direto) |
| `costureiros` | INSERT/UPDATE |

**Lê:** `planejamento_producao` (MRP), `custos_sku` (CMV), `produtos`. Schema em [../SCHEMA.md](../SCHEMA.md).

## 7. Consumo / UI — `compras.html` (8 abas)

| Aba | Função |
|---|---|
| Pipeline | **Painel "Previsão de Recebimento" (30d)** no topo: total de peças + barras por SKU pai + buckets de tempo (atrasado/0-7/8-15/16-30d); clicar num SKU filtra o cronograma. Depois: Gantt + lista por costureiro (OPs ativas). Busca global filtra produto/costureiro/NF/tecido/cor/OP |
| Pagamentos | Régua D+15 (com NF) / D+30 (sem NF) por `data_entrega_real`/`data_prevista`. Suporta `valor_costura_*_maior` (faixa de tamanho) |
| Insumos | Compras de tecido **agrupadas por TECIDO** (consolida NFs). "⇄ Transferir tudo" move todas as NFs do tecido |
| Histórico | 2 visões (toggle): **Cronológico** (cada linha = uma entrega) + **Consolidado** (Costureiro→Produto→Cor com grade proj/entr e drill nas OPs; só OPs com ≥1 entrega) |
| Planejamento | Sugestões MRP. Cards por **nome** (sem SKU pai) + grade **por cor** (top 5). "Ver detalhe" → 3 heatmaps cor×tam (Estoque/Vendas90d/Cobertura) |
| Custos | RPC `recalcular_custos_sku()` + memória de cálculo retrátil por SKU |
| Costureiros e Fornecedores | Performance + cadastro. "+ Cadastrar agora" inline na Nova OP |
| Produtos (30/04) | Cadastro centralizado pai+variantes; flag "fabricação própria" |

**⚠️ JWT autoRefresh (padrão obrigatório):** `compras.html` é o caso canônico do 401 PGRST303 (sessões longas com POSTs). Usar `async getAuthHeaders()` que lê `session.access_token` fresh antes de cada request — **nunca** capturar `AUTH_HEADERS` estaticamente. Aplicar em qualquer dash com forms/POSTs.

**UI:** drawer lateral (`#drawer`) é o padrão de edição (não modal). `drawer-footer handler=null` esconde Excluir. Scroll sincronizado (scrollbar fantasma + drag) no Gantt e Histórico.

## 8. Fluxos críticos (referência rápida — detalhe em [../fusion-sync/MRP.md](../fusion-sync/MRP.md))

- **Criar OP (smart origin):** se costureiro já tem saldo do insumo, só gera `envio_costureiro` pra qty que falta vir do CD.
- **Exclusão/cancelamento de OP:** busca `envio_costureiro` da OP → inverte (`retorno_cd`) → PATCH movs `ordem_producao_id=NULL` (preserva auditoria) → DELETE OP.
- **Entrega Parcial vs Total** (radio): Parcial = INSERT entrega + `consumo_op` proporcional, OP fica `Em Produção`. Total = + PATCH `status='Entregue'` + data (CHECK garante data).
- **Sobra de tecido ao fechar OP (Total)** — não deixar saldo residual no costureiro. Consome o real (`consumo_real_total`, default = `quantidade_tecido_usada`). Depois trata a sobra: **< 1 peça** (< `consumo_por_peca`) → descarte automático (retalho, sem perguntar); **≥ 1 peça** → `prompt` pergunta destino: `1` devolver ao CD (`retorno_cd` par) · `2` manter no costureiro · `3` descartar como retalho (`consumo_op`). Raiz do bug histórico: `quantidade_tecido_usada` é a estimativa do BOM na criação; quando o costureiro recebe o rolo inteiro (> estimativa por ≥1 peça), a diferença sobrava sem tratamento (só o descarte <1pç existia). Fix 05/06.
- **⚠️ Data no Histórico ≠ `data_entrega_real` da OP:** o Histórico é **per-entrega** (`producao_entregas.data_entrega`). Editar "Data de Entrega Real" no form da OP **só** afeta a régua de Pagamentos — não o Histórico, se a OP tiver entregas registradas (`data_entrega_real` só dirige o Histórico no path B, OP sem entregas). Pra corrigir a data exibida no Histórico: editar cada entrega, ou usar o botão **"↧ Aplicar esta data às N entrega(s)"** no form (propaga `data_entrega_real` → todas as `producao_entregas.data_entrega`, só data). Adicionado 02/06 após caso OP #1327.
- **Editar/excluir entrega:** mov de delta / mov reversa; trigger `trg_excluir_op_entrega` decrementa `qtde_pecas_entregues` simétrico.
- **⚠️ Transferir tecido que está em produção (trava 06/06):** OPs criadas por *smart origin* (costureiro já tinha o tecido) **não geram mov própria** — consomem do saldo geral daquele local, sem vínculo reservado entre OP e quantidade. Logo "Transferir"/"Transferir tudo" não distingue tecido livre de tecido comprometido com OP aberta. Guard `opsComprometidasNoLocal(insumoId, local)` (compras.html) detecta OPs ativas (`status NOT IN Entregue/Cancelado`, `costuName(costureiro_id)===origem`) e **avisa+confirma** antes de mover, nos dois fluxos (`transferir-tecido` e `transferir-nf`). CD FUSION nunca tem OP → sempre liberado. Origem do guard: incidente 02/06 (12 NFs movidas às cegas pro MEM CAMISARIA, 8 OPs órfãs).
- **Custos faixa menor/maior:** `costureiros.tamanho_corte_menor_max` + `ordens_producao.valor_costura_*_maior`. `valor_total` = grade_menor×custo_menor + grade_maior×custo_maior.

## 9. Runbook operacional

**Verificar MRP rodou:** `sync_log` fonte `snapshot_produtos`/produção; aba Planejamento com `data_calculo` recente.
**Recalcular custo:** botão "Recalcular" (aba Custos) ou aguardar cron.

| Sintoma | Causa provável | Fix |
|---|---|---|
| Sugestão MRP sumida / velocidade baixa | filtro `ativo=true` cortando variantes (vendas KWID somem ~8%) | split filtro: vendas conta tudo, grade só ativos (fix 02/05) |
| `quantidade_atual` não bate com saldo | PATCH direto em vez de mov, ou trigger off | sempre via `movimentacao_insumos`; `vw_insumo_saldo_local` é a verdade |
| OP `Entregue` sem data | violaria CHECK `chk_entregue_tem_data` | sempre setar `data_entrega_real` ao marcar Entregue |
| Status antigo (`Produzindo`) aparece | regressão de naming | grep cross-repo; só 4 status válidos |
| Custo absurdo (alfaiataria) | cap WAC R$300 + faixa maior fora do CMV | limitação conhecida v6 |
| Conciliação OP×planilha não bate | tolerância/typo/cor sinônima/costureiro sem rastro | ver regras de conciliação abaixo |

**Conciliação OP × `COMPRAS.xlsx`** (fonte: aba CONTROLE COMPRAS): cruzar por costureiro+cor+qtde+data. Tolerância qtde **±30%**; year typo **+365d** (delta -300 a -400); cores sinônimas (AZUL MARINHO≡MARINHO etc); costureiros sem rastro (CONSACRE/ZANUZEN/SIMONE parcial) não conciliam. SIMONE >180d: manter (alfaiataria). Detalhe em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).

## 10. Invariantes & smoke checks (no `compras.html`)

- `'Em Produção'` presente; `'Produzindo'`/`'cancelada'` ausentes.
- `vw_insumo_saldo_local` carregada; `renderReguaPagamentos` presente.
- IDs HTML únicos (`tbody-pagamentos`, `tbody-regua-pagamentos` — não duplicar).
- Sem `'</script>'` literal em string JS (usar `'<scr'+'ipt>'`).
- `jspdf` carregado. Sanity drift `estoque_insumos` vs view = 0.
- Validação completa: skill **`fusion-sanity-check`** (bloco fusion-dash + fusion-sync).

## 11. Variáveis de ambiente

Service `fusion-sync-producao`: `SUPABASE_URL` + `SUPABASE_KEY` (service_role). Dash usa anon JWT (auth.js). Sem credenciais externas (compras é input + cálculo interno).

## 12. Decisões & armadilhas

- **Event-sourcing de tecido** — saldo vive em `movimentacao_insumos`; nunca PATCH `quantidade_atual` direto.
- **`localizacao` guarda o NOME do costureiro (denormalizado) — renomear quebra o saldo.** `movimentacao_insumos.localizacao` e `estoque_insumos.localizacao` armazenam a string do nome (não `costureiro_id`). `vw_insumo_saldo_local` agrupa por essa string; o form de Nova OP busca saldo pelo nome **atual**. Renomear um costureiro deixava o saldo preso no nome antigo → NFs sumiam na abertura de OP. **Protegido desde 10/06 pelo trigger `trg_cascata_rename_costureiro`** (`AFTER UPDATE OF nome ON costureiros` → propaga o novo nome pros dois campos `localizacao`). SQL `sql/2026-06-10_cascata_rename_costureiro.sql`. (Migração one-time de 406 movs + 72 insumos alinhou os renames já feitos pro formato "EMPRESA / PESSOA".)
- **4 status canônicos** — triggers não usam mais valores legados (fix 11/05).
- **SKU pai escondido da UI** — usuário vê só nome do produto; helpers `nomeProduto()`/`categoriaProduto()`.
- **`fabricacao_propria` é flag, não hardcode** — coluna `produtos.fabricacao_propria` é fonte única (antes hardcoded em 3 arquivos: compras.html, estoque.html, fusion_sync_producao.py). Cadastrar produto com a flag entra no MRP no próximo cron.
- **`sb_get` cap 1000 rows** — nunca `limit > 1000` (loop quebra prematuro).
- **WAC v6** (15/05) — custo médio ponderado 90d + IQR trimming + cap R$300; substitui média simples das 2 últimas OPs.
- **WAC v7** (09/06) — **preço-metro = `COALESCE(ordens_compra.valor_metro_kg, estoque_insumos.valor_unitario_referencia, 0)`**. Antes o custo de tecido vinha **só** de `ordens_compra` (via `ordem_compra_id`); OPs modernas pegam tecido por `insumo_id` sem OC → preço-metro nulo → custo_tecido zerava mesmo o insumo tendo preço. Agora cai no preço de referência do insumo (aba Insumos) quando não há OC. Impacto: 4 SKUs saíram do zero (CLDENIM01/CLOX01/CLSPIN01/CMEL01) + WAC mais preciso nos demais (33% das OPs entregues 90d não tinham OC). SQL `sql/2026-06-09_custos_v7_insumo_fallback.sql`. ⚠️ Mexe no CMV do P&L ecommerce (mais preciso). Cron MRP usa a função do DB → já roda v7 sem mudar código.
- **Custo dual dentro/fora + faixa menor/maior** — costureiro cobra diferente por tamanho.

## 13. Histórico de incidentes & memória

- `project_modulo_compras` — MRP inicial
- `project_compras_phase2` / `project_compras_phase3` — refactor OC/OP (4 status, custo dual, event log, entregas parciais)
- `project_compras_sessao_02_05` — Local de estoque, aba Produtos, split filtro, heatmaps
- `project_compras_fix_triggers_11_05` — fix triggers/constraint
- `feedback_mrp_armadilhas` / `feedback_mrp_decisoes_persistentes` — staleness, cadência 1x/dia, SJPREMIUM fora de linha
- `feedback_conciliacao_op_planilha` — regras de conciliação

## 14. Changelog

- **2026-06-17** — **Painel "Previsão de Recebimento" (30d) no topo do Pipeline.** Resolve "quanto vou receber nos próximos 30 dias por SKU" — o Gantt era fragmentado demais por SKU/costureiro pra ler isso. `renderRecebimento30d`: total de peças + barras por SKU pai (pendente = qtde − entregue) + 4 buckets de tempo (atrasado/0-7/8-15/16-30d). **"Quando"** = `data_prevista_entrega` (real) OU `data_envio_tecido + 45d` (lead MRP, estimado, marcado com ~) — necessário porque ~metade das OPs não tem previsão. Inclui atrasados (data esperada já passou). Clicar num SKU filtra o cronograma abaixo (`filtrarPipelinePorProduto`). Peças sem nenhuma data são contadas à parte com aviso.
- **2026-06-16** — **FLAIN cadastrado (Camisa Flanela Infantil).** Buscado na API Tiny (`fio_e_trama`, código FLAIN) → 1 pai + 12 variantes (tam 1/2/3/4/6/8 × cores VERMELHO COM PRETO / PRETO COM BRANCO) + 2 `produto_cores_validas`. Fabricação própria. **Categoria "CAMISA INFANTIL" (nova)** — propositalmente **sem grade oficial** em `gradeOficialDaCategoria`, então `tamanhosDoSKU` cai no fallback e usa os tamanhos reais das variantes (1–8 infantil), em vez da grade adulto P–G1 de CAMISA. **Padrão reutilizável pra qualquer produto infantil**: categoria própria sem regra de grade → grade vem das variantes. Dado vivo na tabela `produtos` (aparece nos dashes após reload, sem deploy); se rodar `carregar_produtos.py` do xlsx, incluir FLAIN no `FUSION_DePara_Final_v4.xlsx` antes.
- **2026-06-16** — **Ajuste de metragem em produção (real do produtor).** Editar OP ganhou campo **"Metragem em produção"** (`quantidade_tecido_usada`) editável. A metragem da abertura é estimativa (cada rolo tem metragem própria); quando o produtor informa o real, a analista ajusta o campo. Como saldo livre = físico − comprometido, **reduzir libera a diferença como saldo livre no próprio costureiro** (decisão Leo 16/06 — sem mov física pro CD). Hint mostra o delta; se a metragem exceder o físico no costureiro, avisa (over-commit). Se fechar como Entregue no mesmo save, o `consumo_op` usa o valor ajustado.
- **2026-06-10** — **Transferência de tecido: atualização instantânea do saldo na tela.** Antes, ao transferir, o dash chamava `carregar()` (14 fetches paralelos) antes de mostrar o saldo novo → demorava. Agora: update **otimista** local de `STATE.saldoLocalIdx` a partir das movs postadas (`aplicarDeltaSaldoLocal`) + `renderInsumos()` instantâneo + reconcile leve em background (`refrescarSaldoInsumos`, 1 query no `vw_insumo_saldo_local`). Aplicado nos 2 fluxos (`transferir-tecido` e `transferir-nf`), que agora dão `return` antes do `carregar()` pesado. Saldo sempre migrou no banco — o problema era só a latência do refresh de tela.
- **2026-06-10** — **Rename de costureiro quebrava saldo no form de OP — corrigido + protegido.** `localizacao` (movs + estoque_insumos) guarda o nome do costureiro; ao renomear pro formato "EMPRESA / PESSOA", o saldo ficou preso no nome antigo → NFs de tecido não apareciam na Nova OP. Migração one-time (406 movs + 72 insumos, mapa old→new via `costureiro_id` das OPs — autoritativo, ex: "LADO A LADO"→"HE / JAIME"). Prevenção: trigger `trg_cascata_rename_costureiro` propaga renames futuros automaticamente. Detalhe na seção 12. Sem mudança de código no dash (só dados + trigger).
- **2026-06-09** — **Memória de cálculo (aba Custos) alinhada à v7 + mostra metragem.** O detalhe por OP (`memoriaCalculoCusto`) calculava custo de tecido **só via OC** — OPs sem OC apareciam "sem compra vinculada (não conta)" mesmo com o insumo tendo preço. Agora usa `COALESCE(OC.valor_metro_kg, insumo.valor_unitario_referencia)` (igual à RPC v7), marca a fonte (OC/cadastro), e a coluna passou a mostrar **metragem consumida (qtd×consumo) · gasto de tecido da OP**. OPs genuinamente sem preço viram linha **laranja** "⚠ cadastrar valor/metro no insumo" (catch do erro real). Validado: 38 tecidos com saldo, **0 sem preço** — a analista cadastra certo; o gap era só o sistema não usar o cadastro nas OPs sem OC.
- **2026-06-09** — **Custo de tecido v7 — fallback pro preço do insumo.** `recalcular_custos_sku` passou a calcular preço-metro como `COALESCE(OC.valor_metro_kg, estoque_insumos.valor_unitario_referencia, 0)` (antes só OC). Resolve produtos com `custo_tecido=0` apesar do insumo ter preço — causa: OPs modernas pegam tecido por `insumo_id` sem criar OC. 4 SKUs saíram do zero, 25 recalculados. Aplicado via psycopg2 + recalc. Detalhe na seção 12. ⚠️ Muda CMV do P&L (mais preciso).
- **2026-06-09** — **Histórico: visão Consolidada por Costureiro × Produto × Cor.** Toggle "Cronológico ↔ Consolidado" na aba Histórico. Consolidado agrupa Costureiro → Produto → Cor; cada cor mostra proj/entregue total + **grade entregue por tamanho** e expande pra lista de OPs com suas entregas (data + grade). ⚠️ Grade por tamanho mostra **só o entregue** (real) — não o projetado por tamanho: ~92% das OPs têm `grade_projetada` nula (a grade só é preenchida na entrega), então projetado-por-tamanho seria sempre `/0`. O comparativo proj×entregue fica no **total** (`qtde_pecas`). Filtros próprios: categoria (cascata→produto), produto, costureiro, busca (sem acento). **Escopo: só OPs com ≥1 entrega, status ≠ Cancelado** — exclui as nunca-entregues (distorceriam) mas mantém parciais (onde se vê a grade evoluir). Grade projetada por tamanho é **estimada** (template de proporção × qtde); entregue é real (soma de `producao_entregas.grade_entregue`). Funções `renderHistoricoConsolidado`/`setHistView`/`toggleConsol`/`popularFiltrosConsol` em compras.html. Sem backend novo (usa `STATE.ops`+`STATE.entregas`).
- **2026-06-08** — **Busca e filtros do Pipeline.** (1) Busca **insensível a acento** (`semAcento` via NFD) — "passa facil" casa com "Passa Fácil". (2) Os **dois** campos de busca (principal + o da lista) agora filtram **cronograma E lista** (antes o da lista só re-renderizava a lista). (3) Cascata **categoria→produto**: selecionar categoria repopula o dropdown de produto só com itens daquela categoria (`popularProdutosPorCategoria`, chamada no load e no onchange da categoria).
- **2026-06-08** — **Fix filtro "SEM DATA DE ENTREGA" (Pipeline).** O chip/KPI dizia "sem data de entrega" mas filtrava por `!data_envio_tecido && !data_prevista_entrega` (as DUAS faltando) — mostrava 1 de 77 OPs. Critério corrigido pra só `!data_prevista_entrega` (a data estimada de entrega não preenchida), batendo com o label: 65 OPs. Trocado em 4 lugares do Pipeline (chip count, KPI count, `renderOPsLista`, gantt). A ocorrência da aba **Pagamentos** (`opsSemData`, "não projeta") foi **mantida** com as duas datas — lá é outro conceito (sem nenhuma data não dá pra projetar pagamento).
- **2026-06-05** — **Nova OP mostra saldo NO COSTUREIRO, não o total.** O dropdown de cor/NF do form de Nova OP passa a filtrar/exibir pelo saldo **físico no costureiro selecionado** (`saldoLivreNoCostureiro(insumoId, costuNome)` = saldo no local do event-log − comprometido em OPs ativas desse costureiro), não o total CD+costureiro. Fluxo Fusion: analista **transfere CD→costureiro e depois abre a OP** — a OP só pode usar o que já está com a costureira; tecido só no CD não aparece (força transferir antes). Trocar o costureiro recalcula as cores (`atualizarTodasCoresRows`). Validação no save também passou a checar contra o saldo no costureiro. Antes mostrava o total (ex: COFFE NF 9238 = 835m em vez dos 263m na DEBORA), confundindo o operador.
- **2026-06-05** — **Metragem visível na OP + travas anti-fantasma.** (1) Pipeline (Lista de Ordens) ganhou coluna **Tecido** = `quantidade_tecido_usada`. (2) Save Nova OP: cor com metragem mas 0 peças (grade vazia) agora **avisa** em vez de pular silencioso — origem dos fantasmas. (3) Check de over-alocação passou a comparar com **saldo LIVRE** (físico − `tecidoEmProducaoDoInsumo`, soma de outras OPs ativas), não só físico total. Limpeza: excluídas 2 OPs fantasmas (1516/1517, 0 peças mas 600m cada, criadas 14/05 sem grade) que inflavam "Em Produção" da NF 195653 pra 1200m num físico de 1005m. Físico nunca esteve errado — só o cálculo de Em Produção/Saldo Livre. ⚠️ `grade_projetada` é **template de proporção**, não contagem (grade_soma≠qtde_pecas é normal).
- **2026-06-05** — **Sobra de tecido ao fechar OP — prompt destino.** Fechamento Total agora trata a sobra ≥1 peça com `prompt` (devolver CD / manter / descartar) em vez de deixar parada no costureiro; <1 peça segue descarte automático (seção 8). Limpeza legado: 3 retalhos zerados (DEBORA NF 64097 6,2m, RM MACHADO ×2 54m — movs 795-797). 3 sobras grandes (MF PAZUCH 835/456m, LADO A LADO 450m) mantidas no costureiro; OP 950 SIMONE intacta (alocada à OP ativa 1343).
- **2026-06-05** — **ALFPV associado ao poliviscose.** `skus_pai` dos 4 insumos NF 9238 (`69%POL.29%VISC.2%ELAST.`) ganhou `ALFPV` + BOM `consumo_tecido` ALFPV→tecido = 1,20 m/peça (id 144). Calça Alfaiataria de Poliviscose passa a poder abrir OP com esse tecido.
- **2026-06-05** — **Incidente + trava de transferência.** Funcionária usou "⇄ Transferir tudo" e moveu 12 NFs de Rovacel de uma vez pro costureiro MEM CAMISARIA (NF remessa interna 136783), incluindo tecido em produção em 8 OPs abertas de *outros* costureiros (LADO A LADO/PADOVA/GJ CAETANO) → OPs órfãs de tecido. **Reversão:** 12 pares compensatórios (24 movs, IDs 771-794) devolvendo cada insumo à origem pré-02/06 — sem deletar movs (preserva auditoria). Event-log restaurado, MEM CAMISARIA zerado do lote. **Prevenção:** guard `opsComprometidasNoLocal` avisa+confirma ao transferir tecido em produção (seção 8). ⚠️ Lembrete: `estoque_insumos.localizacao` é só a localização de *cadastro* — **não** é atualizada por transferência; a verdade da localização física é sempre `vw_insumo_saldo_local` (event-log).
- **2026-06-02** — Form Editar OP: nota + botão "↧ Aplicar esta data às N entrega(s)" quando a OP tem entregas parciais (`aplicarDataEntregaRealEntregas`). Resolve armadilha em que editar `data_entrega_real` não mexia no Histórico (per-entrega). Caso disparador: OP #1327 (2 entregas corrigidas 29/04→29/05 direto no banco). Commit `317db85`.
- **2026-05-15** — Custo WAC v6 (média ponderada 90d + IQR + cap R$300) — `sql/2026-05-15_custos_v6_wac.sql`.
- **2026-05-11** — fix 3 bugs triggers/constraint (status canônicos, AFTER DELETE entregas, `chk_entregue_tem_data`).
- **2026-05-02** — aba Produtos centralizada, `fabricacao_propria` flag, split filtro MRP, heatmaps cor×tam.
- **2026-04-26/27** — Phase 2/3: 4 status, custo dual, `movimentacao_insumos` event-sourced, entregas parciais, régua D+15/D+30.
