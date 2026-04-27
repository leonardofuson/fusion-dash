# COMPRAS — Dash de Input (sistema OC/OP)

> Único dash que **escreve** no banco — registra Ordens de Compra (tecido/aviamento) e Ordens de Produção. Padrões totalmente diferentes dos dashes de leitura. Convenções compartilhadas (Chart.js, JWT, mobile) em [CLAUDE.md](CLAUDE.md). Lógica de MRP/cobertura/sugestões em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).

## Estrutura

Arquivo: [`compras.html`](compras.html) (~3800 linhas, maior arquivo do projeto). 7 abas:

| Aba | Função |
|---|---|
| Pipeline | Gantt por costureiro — OPs ativas em janela de tempo. Botão "📦 Registrar entrega" no footer do drawer de Editar OP (só aparece se tem saldo pendente) |
| Pagamentos | Régua D+15 (com NF) / D+30 (sem NF) baseada em `data_entrega_real` ou `data_prevista_entrega` |
| Insumos | Compras de tecido (OCs) — coluna "Localização" + botões Editar/Alocar/Excluir por linha |
| Histórico | Listagem cronológica de OCs/OPs com filtros e drag-to-scroll |
| Planejamento | Sugestões do MRP (`planejamento_producao`) — botões "Criar OP" e "Comprar tecido" pré-preenchem drawer |
| Custos | RPC `recalcular_custos_sku()` — botão "Recalcular" força refresh manual |
| Fornecedores | Cadastro |

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
| `compra` | Cadastro de novo insumo | + | localização default |
| `saldo_inicial` | Backfill / migração | + | local atual |
| `envio_costureiro` | Criar OP (par -CD/+costureiro) ou "Alocar" sem OP | par neg/pos | CD FUSION → costureiro |
| `consumo_op` | Entrega parcial ou total registrada | − | costureiro (proporcional `qty × consumo_por_peca`) |
| `retorno_cd` | Cancelamento ou exclusão de OP — espelha as `envio_costureiro` originais (sinal oposto, mesma localização) | par invertido | volta pro local de origem |
| `ajuste_compra` | Editar "Total Comprado" no drawer de Insumo | ± delta | localização default |

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
