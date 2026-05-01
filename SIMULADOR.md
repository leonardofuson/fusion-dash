# Simulador — Calculadora de Preço/Margem

> Dash em [`simulador.html`](simulador.html). Pipeline de dados em [`../fusion-sync/CLAUDE.md`](../fusion-sync/CLAUDE.md) (`snapshot_produtos.py` + `fit_curva_ads.py`). Schema em [`../SCHEMA.md`](../SCHEMA.md).

## Objetivo

Ferramenta operacional pros gestores de conta (ML, TikTok, Shopee, Site Próprio) decidirem:
1. Quanto cobrar em cada produto por canal (calculadora de margem)
2. Quanto investir em ads em cada canal (curva ótima)
3. Avaliar impacto de ações passadas (mudança de foto/texto/preço/budget) — antes/depois

> **Não substitui o dash de Marketing** (parqueado no Plano Mestre). Esse simulador é tático/transacional: input/cenários do dia-a-dia. O dash de Marketing seria estratégico (CAC, atribuição multi-canal, LTV).

## Abas

| Aba | Função | Tabela/View principal |
|---|---|---|
| **Calculadora** | Input SKU+canal+preço+ads → margem líquida com breakdown | `produtos`, `canal_custos_faixa`, `vw_taxa_devolucao_*`, `vw_frete_medio_*` |
| **Curva Ótima de Ads** | Gráfico gasto×lucro líquido com fit log + ponto sugerido | `ads_curva_otima` |
| **Antes / Depois** | Timeline de eventos + delta 14d × 14d (qty, receita, devs) | `produto_evento`, `pedidos`, `itens_pedido` |
| **Cenários Salvos** | Lista RLS, comparação 2x2, export PDF | `simulacao_cenarios` |

## Fórmula de margem

```
preco_bruto         = input do gestor
desconto_cupom      = preco × cupom_pct  (só Site Próprio)
receita_liquida     = preco_bruto − desconto_cupom + rebate

comissao            = preco_bruto × comissao_pct(faixa) + taxa_fixa(faixa)
                      [+ taxa_extra_pct se afiliado TikTok]
cmv                 = produtos.custo_total
frete               = média histórica (60d) por SKU+canal_raw, fallback canal
devolucao_estim     = preco_bruto × taxa_devolucao_estimada (90d, fallback canal)
ads                 = input direto
custos_fixos        = receita_liquida × fixo_pct (default 8%)

margem_liquida      = receita_liquida − comissao − cmv − frete − devolucao_estim − ads − custos_fixos
margem_pct          = margem_liquida / receita_liquida × 100
```

**Por que `comissao` é em cima do preço bruto e não da receita líquida?** Plataformas cobram em cima do preço cheio — desconto de cupom não reduz a base de comissão.

## Lookup de comissão por faixa

`canal_custos_faixa` armazena 8 linhas com `canal_pattern` (LIKE) + `faixa_min` / `faixa_max` + `comissao_pct` + `taxa_fixa`. Calculadora itera achando primeira faixa que casa o pattern do canal_label E onde `faixa_min ≤ preço < faixa_max` (ou `faixa_max IS NULL`).

| Canal label | Pattern | Faixas |
|---|---|---|
| Mercado Livre | `Mercado Livre%` | < R$79,99 (14% + R$7,95) / ≥ R$79,99 (14% + R$18) |
| Shopee | `Shopee%` | < R$79,99 (20% + R$4) / R$79,99–99,98 (14% + R$16) / ≥ R$99,99 (14% + R$20) |
| Shein | `Shein%` | 16% + R$4 (sem faixa) |
| TikTok Shop | `TikTok%` | 6% + R$4 + 6% sobre frete (afiliado opcional adiciona +12%) |
| Site Próprio | `Site Próprio%` | 12,1% consolidado (Shopify 1% + gateway 5,45% + comissões 2,15% + frete 2% + provisão dev 1,5%) |

> Atualizar fonte da verdade ([CUSTOS_POR_CANAL.md](../CUSTOS_POR_CANAL.md)) E re-rodar `sql/2026-05-01_canal_custos_faixa.sql` (TRUNCATE+INSERT) quando comissões mudarem.

## Curva ótima de ads — interpretação

Modelo: `lucro = a + b·ln(gasto + 1)` ajustado por mínimos quadrados em `fit_curva_ads.py`. Derivada: `b/(gasto+1)`. Ponto ótimo onde derivada = 1 → `gasto* = b - 1`.

- **b ≤ 1**: marginal já é < R$1 desde o início — não vale subir gasto. Sistema mostra `ponto_otimo = 0`.
- **R² < 0.3**: fit fraco (gasto não correlaciona bem com lucro nominal). UI exibe alerta amber. Não tratar como recomendação dura.
- **Amostra < 30 dias**: poucas observações, intervalo de confiança grande.

> Fit é apenas por **canal+plataforma** no MVP. SKU-level requer resolução `item_id ML → produto_id` que ainda não está consolidada em `ads_metrics`.

## Tracking de mudanças (snapshot + diff)

`snapshot_produtos.py` roda diariamente capturando estado dos anúncios:
- **ML (FIO + Confecções)**: `/items` API + `/items/{id}/description` — preço, hash(descricao), hash(lista de URLs de fotos)
- **Shopify**: `/admin/api/products` — mesmo schema

D-1 vs D detecta mudanças e gera `produto_evento` com `fonte='auto_*'`. Limitação: hash não diferencia tipo de mudança (ex: troca de ângulo da foto principal vs reupload sem mudança visual real).

Por isso o **fluxo híbrido**: o gestor pode marcar **eventos manuais** via UI (drawer "Marcar evento") com tipo + descrição + data — fica em `produto_evento` com `fonte='manual'` e `criado_por=user_id`. Útil pra anotar:
- Mudança de ângulo/composição de foto sem reupload
- Eventos contextuais (entrada em campanha, mudança de tom de copy)
- Mudanças fora da plataforma (budget Meta Ads, evento promocional)

> Shopee/Shein/TikTok **não têm snapshot automático** ainda — só evento manual.

## Cenários salvos (`simulacao_cenarios`)

Cada gestor vê só seus cenários (RLS por `user_id = auth.uid()`). Estrutura `inputs JSONB` + `outputs JSONB` permite rastrear evolução do raciocínio sem rigidez de schema. UI suporta:
- Comparar 2 cenários (delta linha a linha)
- Exportar PDF (jsPDF, lista compacta)
- Deletar individualmente

## Limitações conhecidas

1. **Meta + Google Ads não populam `ads_curva_otima` ainda** — esperando credenciais. Quando entrarem, basta o cron `fit_curva_ads.py` rodar e curvas aparecem automaticamente (filtro plataforma já existe na UI).
2. **Rebate da plataforma** é input manual — schema não tem campo automatizado.
3. **Snapshot não cobre Shopee/Shein/TikTok** (APIs não confirmadas pra produto). Eventos só manuais nesses canais.
4. **Curva ótima é por canal, não SKU** — granularidade fina exige resolução SKU em ads_metrics que ainda é parcial.
5. **Comparação antes/depois usa só pedidos vivos (60d)** — eventos > 30 dias ficam parcialmente cortados na janela `+14d`.
6. **CMV é por SKU pai** — variações de cor/tamanho compartilham o mesmo `produtos.custo_total`. Como o ERP da Fusion sempre tratou.

## Permissionamento

Acesso por `user_roles.dashes` contendo `'simulador'`. RLS garante isolamento de cenários por user (cada gestor vê só os próprios). Eventos manuais e snapshot são leitura aberta a authenticated.

Liberar acesso:
```sql
UPDATE user_roles SET dashes = array_append(dashes, 'simulador')
WHERE email = '...' AND NOT 'simulador' = ANY(dashes);
```
