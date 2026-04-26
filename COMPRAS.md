# COMPRAS — Dash de Input (sistema OC/OP)

> Único dash que **escreve** no banco — registra Ordens de Compra (tecido/aviamento) e Ordens de Produção. Padrões totalmente diferentes dos dashes de leitura. Convenções compartilhadas (Chart.js, JWT, mobile) em [CLAUDE.md](CLAUDE.md). Lógica de MRP/cobertura/sugestões em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).

## Estrutura

Arquivo: [`compras.html`](compras.html) (~183 KB, maior arquivo do projeto). 6 abas:

| Aba | Função |
|---|---|
| Pipeline | Gantt por costureiro — OPs ativas em janela de tempo |
| Costureiros | Cadastro/edição de facções (capacidade, SKUs habilitados) |
| Insumos | Compras de tecido (OCs) — drawer de cadastro/edição |
| Planejamento | Sugestões do MRP (`planejamento_producao`) — botões "Criar OP" e "Comprar tecido" pré-preenchem drawer |
| Custos | RPC `recalcular_custos_sku()` — botão "Recalcular" força refresh manual |
| Histórico | Listagem cronológica de OCs/OPs com filtros e drag-to-scroll |

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
| `ordens_compra` | INSERT (Insumos: nova compra de tecido), UPDATE (edição), soft-delete |
| `ordens_producao` | INSERT (Planejamento: criar OP, ou direto), UPDATE (registrar entrega parcial, mudar status) |
| `costureiros` | INSERT/UPDATE (Costureiros: cadastro de facção) |
| `estoque_insumos` | INSERT/UPDATE (entrada de tecido) — derivado de `ordens_compra` |

Schema das tabelas em [../SCHEMA.md](../SCHEMA.md). Vocabulário de status em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).

## Cache local de preço por costureiro/SKU

Aba Histórico mantém cache do **último `valor_peca` conhecido por costureiro + SKU pai** (lookup via `sku_produto` e via produto textual) — usado pra autopreencher drawer de nova OP. Linha ~1848.

## Recalcular custos (botão Custos)

Chama RPC `recalcular_custos_sku()` no Supabase. Após sucesso, recarrega aba. Custo flui pra `custos_sku` → `produtos.custo_total` → outros dashes (ecommerce consome via `produtos.custo_total`).
