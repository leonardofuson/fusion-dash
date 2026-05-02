# COMPRAS — Dash de Input (sistema OC/OP)

> Único dash que **escreve** no banco — registra Ordens de Compra (tecido/aviamento) e Ordens de Produção. Padrões totalmente diferentes dos dashes de leitura. Convenções compartilhadas (Chart.js, JWT, mobile) em [CLAUDE.md](CLAUDE.md). Lógica de MRP/cobertura/sugestões em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).

## Estrutura

Arquivo: [`compras.html`](compras.html) (~6000 linhas, maior arquivo do projeto). 8 abas:

| Aba | Função |
|---|---|
| Pipeline | Gantt + Lista por costureiro — OPs ativas. **Busca global** filtra produto/costureiro/NF/tecido/cor/OP simultaneamente nas duas. Chip "SEM DATA DE ENVIO" + filtros produto/costureiro/status |
| Pagamentos | Régua D+15 (com NF) / D+30 (sem NF) baseada em `data_entrega_real` ou `data_prevista_entrega`. Suporta `valor_costura_*_maior` (faixa de tamanho — 02/05) |
| Insumos | Compras de tecido **agrupadas por TECIDO** (consolida múltiplas NFs do mesmo tecido). Header mostra contagem de NFs; expand mostra lotes (cor × NF). Botão "⇄ Transferir tudo" no header move TODAS as NFs do tecido em lote. Cores Editar/Transferir/Excluir por linha |
| Histórico | Listagem cronológica de OCs/OPs com filtros e drag-to-scroll |
| Planejamento | Sugestões do MRP. Filtros: busca + categoria + prioridade. Cards mostram **só nome do produto** (sem SKU pai), com **grade sugerida POR COR** (top 5 cores). Botão "Ver detalhe" abre drawer com **3 heatmaps cor × tamanho** (Estoque / Vendas 90d / Cobertura em dias). CTAs "Abrir OP" / "Comprar tecido" pré-preenchem drawer |
| Custos | RPC `recalcular_custos_sku()` — botão "Recalcular" força refresh manual |
| Costureiros e Fornecedores | Performance + cadastro/edit. Click numa linha de costureiro abre drawer em modo edit. Atalho na Nova OP: digitando nome inexistente, link "+ Cadastrar agora" |
| **Produtos** (novo, 30/04) | Cadastro centralizado. Lista todos os produtos pai. Drawer cadastrar/editar (nome, SKU pai manual, categoria, range de tamanhos auto-preenchido, cores texto livre, flag "fabricação própria"). Save cria 1 pai + N variantes (cor × tamanho). Edit permite toggle ativo nas variantes (não delete — preserva FK) e adicionar cores novas |

## ⚠️ JWT autoRefresh — padrão obrigatório

`compras.html` é o **caso canônico** do problema 401 PGRST303 — sessões longas com múltiplos POSTs (form drawer aberto por minutos). Padrão em [compras.html:567-580](compras.html#L567):

```js
async function getAuthHeaders() {
  // Sempre lê o token atual da sessão do SDK (autoRefreshToken gerencia em memória)
  const session = await fusionAuth.getSession();
  return { 'Authorization': 'Bearer ' + session.access_token, ... };
}

// USO em todo POST:
const r = await fetch(url, {
  method: 'POST',
  headers: Object.assign({'Content-Type':'application/json'}, await getAuthHeaders()),
  body: JSON.stringify(...)
});
```

**Nunca** capturar `AUTH_HEADERS` estaticamente. Aplicar esse padrão em qualquer dash novo que tenha forms/POSTs.

## Padrões de UI específicos

- **Drawer lateral** (`#drawer`) é o padrão de edição/cadastro — não modal, não inline. Configurar `drawer-footer` com `handler=null` esconde o botão Excluir.
- **Cores de produto** mapeadas em objeto fixo no topo do bloco Pipeline (linha ~681) — referência visual no Gantt.
- **Sincronização de scroll** (Gantt e Histórico): scrollbar fantasma sticky no topo + drag-to-scroll no body. Função `sincronizarScrollbars` reusada em ambas abas.

## Tabelas que escreve

| Tabela | Operações |
|---|---|
| `ordens_producao` | INSERT (Planejamento ou Nova OP), UPDATE (edição/transição de status), DELETE (com inversão de movs) |
| `producao_entregas` | INSERT (entrega parcial/total), UPDATE (corrigir entrega passada), DELETE (cancelar entrega) |
| `movimentacao_insumos` | INSERT (todos os fluxos abaixo geram event log), DELETE (só ao excluir insumo) |
| `estoque_insumos` | INSERT (nova compra), PATCH (edição metadados — saldo NÃO é editado direto) |
| `costureiros` | INSERT/UPDATE |

Schema das tabelas em [../SCHEMA.md](../SCHEMA.md). Vocabulário de status em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).

## Fluxos críticos (movimentação de tecido)

**Princípio**: `estoque_insumos.quantidade_atual` é mantido por trigger em `movimentacao_insumos`. **NUNCA fazer PATCH direto** em `quantidade_atual` — sempre via mov, pra preservar audit trail.

### Tipos de mov ([compras.html](compras.html))

| `tipo_mov` | Quando | Sinal | Localização |
|---|---|---|---|
| `compra` | Cadastro de novo insumo (gerada automaticamente desde 28/04 — antes só PATCH em quantidade_atual) | + | campo "Local de estoque" do form (default CD FUSION; pode ser direto pra costureiro) |
| `saldo_inicial` | Backfill / migração | + | local atual |
| `envio_costureiro` | Criar OP (par -origem/+destino) ou Transferir (CD↔costureiro / costureiro↔costureiro) | par neg/pos | conforme |
| `consumo_op` | Entrega parcial ou total registrada | − | costureiro (proporcional `qty × consumo_por_peca`). Usa `COALESCE(quantidade_tecido_usada, metros_kg)` desde 29/04 |
| `retorno_cd` | Cancelamento ou exclusão de OP — espelha as `envio_costureiro` originais. Também usado em Transferir → CD | par invertido | volta pro local de origem real |
| `ajuste_compra` | Editar "Total Comprado" no drawer de Insumo | ± delta | localização default |

**Coluna `nf_remessa`** (28/04): NF Fusion Remessa emitida quando tecido sai do CD pra costureiro. Persiste no par de movs (Transferir + Nova OP). Obrigatória nesse fluxo, opcional nos demais. Aparece no histórico do drawer de Editar Insumo em destaque indigo.

### Criação de OP (smart origin)
Se costureiro **já tem saldo** do insumo (ex: pré-alocado via "Alocar tecido"), nenhuma `envio_costureiro` é gerada — só pra qty que **falta vir do CD**. Isso garante que o retorno na exclusão coloca o tecido onde realmente estava.

### Exclusão de OP / cancelamento
1. Busca movs `envio_costureiro` com `ordem_producao_id=<X>`
2. Inverte cada uma (sinal oposto, mesma `localizacao`) — gera mov `retorno_cd`
3. Para exclusão: PATCH movs históricas → `ordem_producao_id=NULL` (preserva auditoria, libera FK)
4. DELETE OP

### Entrega parcial
Drawer "Registrar entrega" tem radio **Parcial / Total**:
- **Parcial**: INSERT em `producao_entregas` + mov `consumo_op` proporcional (`qty × consumo_por_peca`). OP fica `Em Produção`.
- **Total**: mesmas ações + PATCH OP com `status='Entregue'`, `data_entrega_real`, `mes_ano_entrega`. Preview de diff (projetado vs total) antes de salvar.

### Editar / excluir entrega passada
Cada item do histórico tem botões `Editar` e `Excluir`:
- **Editar**: PATCH `producao_entregas` + mov de delta (`(qty_nova − qty_antiga) × consumo_por_peca`) — sinal flip pra ajustar saldo do costureiro.
- **Excluir**: mov reversa (`+qty × consumo_por_peca`) + DELETE em `producao_entregas`. Trigger DB recalcula `qtde_pecas_entregues`.

## Histórico de movimentações
Drawer de Editar Insumo carrega últimos 200 movs daquele insumo via `movimentacao_insumos?insumo_id=eq.X&order=criado_em.desc`. Mostra Data / Tipo / OP / Local / Qtd / Observação. **Único lugar** pra auditar o event log — futuramente pode replicar no drawer de Editar OP.

## Cache local de preço por costureiro/SKU

Aba Histórico mantém cache do **último `valor_peca` conhecido por costureiro + SKU pai** (lookup via `sku_produto` e via produto textual) — usado pra autopreencher drawer de nova OP. Linha ~1848.

## Recalcular custos (botão Custos)

Chama RPC `recalcular_custos_sku()` no Supabase. Após sucesso, recarrega aba. Custo flui pra `custos_sku` → `produtos.custo_total` → outros dashes (ecommerce consome via `produtos.custo_total`).

## Custos de costura — faixa menor / maior (29-30/04/2026)

Costureiros podem cobrar valores diferentes pra grade pequena vs grande (ex: Clederson 38-50 menor / 52+ maior; Sta Rita 44-58 menor / 60-66 maior). Implementação:

- **`costureiros.tamanho_corte_menor_max int`** (nullable). Define até onde vai a faixa "menor"; >X cai na "maior". NULL = sem distinção.
- **`ordens_producao.valor_costura_dentro_maior` + `valor_costura_fora_maior`** (numeric, nullable). Os legados `valor_costura_dentro/fora` viram a faixa "menor".
- **Forms Nova OP / Editar OP**: revelam seção "Custo grade maior" automaticamente quando o costureiro selecionado tem corte definido. Campos: dentro / fora / total readonly auto-calculado.
- **Auto-fill**: ao mudar costureiro+produto, busca a última OP do mesmo (costureiro_id, sku_produto) e pré-preenche os 4 valores de custo. Só preenche se input estiver vazio (não sobrescreve digitação).
- **`valor_total` da OP**: calculado via `distribuirGradePorCorte()` × valor de cada faixa: `qtd_grade_menor × custo_menor + qtd_grade_maior × custo_maior`.

## SKU pai escondido da UI (29-30/04/2026)

Decisão: usuários enxergam só o **nome do produto**, nunca o código SKU pai. Refactor em todas as abas:
- Helpers `nomeProduto(skuPai)` e `categoriaProduto(skuPai)` em compras.html
- `nomeProduto`: prefere o registro raiz (`sku === sku_pai`); pra SKUs sem raiz, trunca o nome no primeiro " - " (ex: "CALÇA DE MALHA - 44 - VERDE" → "Calça de Malha")
- Datalist Nova OP, Edit OP select, Pipeline lista, CMV/Custos, cards Planejamento — todos exibem só nome
- `extrairSkuProduto()` continua resolvendo (1) "Nome (SKU)" legado, (2) nome → sku_pai via lookup, (3) SKU direto

## Whitelist `SKU_FINALIZADOS` — dinâmica via flag (30/04/2026)

Antes hardcoded em 3 arquivos. Agora:
- Coluna `produtos.fabricacao_propria boolean default false`. Backfill marcou os 21 SKUs canônicos.
- `compras.html`: `isFabricacaoPropria(sku)` lê de `STATE.produtos`. Shim `SKU_FINALIZADOS.indexOf()` mantém compat.
- `estoque.html`: computa `Set` live no fetch.
- `fusion_sync_producao.py`: `load_skus_finalizados()` no `main()`.
- **Aba Produtos** com checkbox "Fabricação própria" controla a flag — cadastrar/editar atualiza a whitelist em todo o ecossistema no próximo ciclo.
