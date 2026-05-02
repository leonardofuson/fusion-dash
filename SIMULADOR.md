# Simulador — Calculadora de Preço/Margem + Eficiência de Ads

> Dash em [`simulador.html`](simulador.html). Pipeline em [`../fusion-sync/CLAUDE.md`](../fusion-sync/CLAUDE.md) (`snapshot_produtos.py` + `fit_curva_ads.py` + scripts de mapping ML). Schema em [`../SCHEMA.md`](../SCHEMA.md).

## Objetivo

Ferramenta operacional pros gestores de canal (ML, TikTok, Shopee, Site Próprio) decidirem:
1. Quanto cobrar em cada produto por canal (calculadora de margem)
2. Quanto investir em ads em cada canal/SKU (curva de retornos + ROAS histórico)
3. Avaliar impacto de ações passadas (mudança de foto/texto/preço/budget) — antes/depois
4. Salvar cenários para comparação e tomada de decisão

> **Não substitui o dash de Marketing** (parqueado no Plano Mestre). Esse simulador é tático/transacional. O dash de Marketing seria estratégico (CAC, atribuição multi-canal, LTV).

## Abas

| Aba | Função | Tabela/View principal |
|---|---|---|
| **1. Calculadora** | Input SKU+canal+preço+ads → margem líquida com breakdown. Filtro de categoria. | `produtos`, `canal_custos_faixa`, `vw_taxa_devolucao_*`, `vw_frete_medio_*` |
| **2. Curva Ótima de Ads** | Timeline temporal (principal) + curva de retornos (recolhida). Filtro de categoria + SKU pai. | `ads_curva_otima` (com `historico jsonb`) |
| **3. Antes / Depois** | Timeline de eventos (auto+manual) + delta 14d × 14d. Filtro de categoria. | `produto_evento`, `pedidos`, `itens_pedido` |
| **4. Cenários Salvos** | Lista RLS, comparação 2x2, export PDF | `simulacao_cenarios` |
| **5. Drifts ML** | Discrepâncias planilha DePara × API ML. Resolução manual. | `ml_item_sku_drift`, `ml_item_sku_map` |

## Princípios de design

1. **Tudo no SKU pai** — anúncios ML, mapping, curva ótima, eventos. Variantes (cor/tamanho) agregam no pai. ML não permite campanha por filho.
2. **Insumos excluídos** — categorias `TECIDO` e `TROCA` nunca entram em listas (244 SKUs pai elegíveis em 8 categorias).
3. **Histórico em primeiro plano** — gráfico principal é cronológico (data×receita); ponto ótimo é referência matemática secundária.
4. **Receita atribuída pela ML** — não receita total do SKU. Isola efeito de ads de orgânico.
5. **Faixa praticada visível** — sistema sinaliza quando o ponto ótimo extrapola o que o gestor já testou na prática.

## Aba 1 — Calculadora

### Fórmula de margem

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

> **Por que `comissao` é em cima do preço bruto?** Plataformas cobram em cima do preço cheio — desconto de cupom não reduz a base de comissão.

### Lookup de comissão por faixa (`canal_custos_faixa` — 8 linhas seed)

| Canal label | Pattern | Faixas |
|---|---|---|
| Mercado Livre | `Mercado Livre%` | < R$79,99 (14% + R$7,95) / ≥ R$79,99 (14% + R$18) |
| Shopee | `Shopee%` | < R$79,99 (20% + R$4) / R$79,99–99,98 (14% + R$16) / ≥ R$99,99 (14% + R$20) |
| Shein | `Shein%` | 16% + R$4 (sem faixa) |
| TikTok Shop | `TikTok%` | 6% + R$4 + 6% sobre frete (afiliado opcional adiciona +12%) |
| Site Próprio | `Site Próprio%` | 12,1% consolidado (Shopify 1% + gateway 5,45% + comissões 2,15% + frete 2% + provisão dev 1,5%) |

> Atualizar fonte da verdade ([CUSTOS_POR_CANAL.md](../CUSTOS_POR_CANAL.md)) E re-rodar `sql/2026-05-01_canal_custos_faixa.sql` (TRUNCATE+INSERT) quando comissões mudarem.

### Filtros de produto

- Dropdown "Categoria" reduz lista de SKUs ao escolher (ACESSÓRIOS, BERMUDA, BLAZER & TERNO, CALÇA, CALÇADOS, CAMISA, CAMISETA, INVERNO)
- Datalist de SKU mostra `sku · nome · categoria`
- Ao trocar categoria, SKU atual é limpo se não pertencer

## Aba 2 — Curva Ótima de Ads

### Layout (reorganizado em 02/05/2026)

**Gráfico principal (topo):** timeline temporal — evolução cronológica
- Eixo X: data (mais antigo → mais recente)
- Eixo Y esquerdo: métrica selecionada (Receita / ROAS / Lucro atrib.) — toggle
- Eixo Y direito: investimento em barras translúcidas indigo
- Linha cyan fina = valor diário; linha grossa = média móvel 7d (fill)
- **Marcadores amber** ◆ no eixo X = eventos do `produto_evento` daquele SKU. Toggle "📍 Eventos" liga/desliga.

**`<details>` recolhível abaixo:** "📐 Curva de retornos decrescentes" — referência teórica
- Scatter gasto×receita atribuída (cada ponto é um dia)
- Linha tracejada = fit log da receita
- Linha verde = faixa praticada (até gasto_max histórico)
- Linha amber vertical = ponto ótimo de gasto (calculado em cima do fit do **lucro**, não receita)
- Lazy render: só monta o Chart quando user expande

### Card lateral — KPIs

```
💰 Janela 90d (atribuição ML)
Receita atribuída: R$ X     ROAS: X.XXx
Investimento: R$ Y
Lucro líquido atribuído: R$ Z (margem M%)
Direta: R$ A · N un  ·  Indireta: R$ B · M un

Antes vs Agora — 45d cada
Antes: 02/02 → 18/03  ·  Agora: 19/03 → 01/05
Gasto médio: ▲ +X%
Receita atrib.: ▲ +Y%
Lucro atrib.: ▲ +Z%

📊 Médias diárias
🧮 Referência teórica do fit
   Ponto ótimo de gasto · R²
▾ Como o lucro é calculado? (expandível)
```

### Cálculo do lucro atribuído

Diferença crítica do que era antes (lucro do SKU inteiro, contaminado por orgânico):

```
lucro_atribuido = receita_atribuida × (1 − comissão_canal − cmv_unitário) − gasto
```

Onde:
- `receita_atribuída` = `direct_amount + indirect_amount` da API ML
- `comissão_canal` = % efetiva derivada do que vendeu no dia (canal_custos_faixa por faixa)
- `cmv_unitário` = % derivado de produtos.custo_total via itens_pedido do dia
- Não inclui frete, fixos, devoluções (subtraídas separadamente)

### Modelo do fit + ponto ótimo

Dois fits log salvos por (SKU pai, plataforma):
- `params.{a, b}` — fit do **lucro atribuído** (define ponto ótimo)
- `params.{ar, br}` — fit da **receita atribuída** (linha do scatter)

Ponto ótimo: derivada de `lucro = a + b·ln(gasto+1)` = 1 → `gasto* = b - 1`.

**Faixa de validade do fit:** linha tracejada do scatter só desenhada de `gasto_min` até `gasto_max × 1.3`. Extrapolar pra esquerda gera valores absurdos (intercepto negativo). Eixo Y com `min: 0` explícito.

**Aviso `extrapola_otimo`:** quando `ponto_otimo > gasto_max × 1.5`, sinaliza que alcançar esse gasto exigiria capacidade operacional não testada (estoque, tráfego, conversão).

### Toggle de métricas (segmented control)

Botões `class="seg-btn"` — **NÃO** usar `class="tab-btn"` (handler global de troca de aba dispara junto). Listener delegado com `preventDefault + stopPropagation`.

Default = Receita (mais intuitivo). Re-render só atualiza a timeline (cache em `STATE.curvaAtual`), não recria o scatter.

## Aba 3 — Antes / Depois

### Tracking de mudanças (snapshot + diff + manual)

`snapshot_produtos.py` (cron 08h BRT) captura diariamente:
- **ML (FIO + Confecções)**: `/items` API + `/items/{id}/description` — preço, hash(descricao), hash(lista de URLs)
- **Shopify**: `/admin/api/products` — mesmo schema

D-1 vs D detecta mudanças e grava `produto_evento` com `fonte='auto_ml_fio'`/`'auto_ml_confec'`/`'auto_shopify'`.

**Limitação do hash:** não diferencia tipo de mudança (troca de ângulo da foto principal vs reupload sem mudança visual real).

**Fluxo híbrido (decisão 01/05):** gestor marca eventos manuais via UI com tipo + descrição + data. `fonte='manual'`, `criado_por=auth.uid()`. Útil pra:
- Mudanças que o hash não captura bem
- Eventos contextuais fora da plataforma (budget Meta, campanhas externas)
- Mudanças em Shopee/Shein/TikTok (sem snapshot automático ainda)

### Comparação 14d × 14d

Ao clicar num evento, mostra:
- Pedidos / Unidades / Receita / Devoluções
- Δ absoluto e % com setas ▲▼
- Aviso: janela curta (28d total) — sinal só confiável com ≥30 pedidos

## Aba 4 — Cenários Salvos

Cada gestor vê só seus cenários (RLS por `user_id = auth.uid()`). Estrutura `inputs JSONB` + `outputs JSONB`:
- Comparar 2 cenários (delta linha a linha)
- Exportar PDF (jsPDF, lista compacta)
- Deletar individualmente

## Aba 5 — Drifts ML (mapping)

Discrepâncias entre `FUSION_DePara_Final_v4.xlsx` e o que API ML retorna pra `seller_custom_field`. Categorias:

| Categoria | Tratamento |
|---|---|
| 🟡 Variante (DePara=pai, API=filho) | Esperado em anúncios de variação (ex: `CMGPD` × `CMGPD-3`). Após fix de promoção pra pai, raros |
| ⚪ Agrupado | Anúncio multi-categoria (sku_api='Agrupado'). Normalmente "ignorado" |
| 🔴 OUTRO | Erro de cadastro real (ex: DePara=`GPDN01`, API=`CMGPD`). Revisar manualmente |

Botões inline pra resolver: `manter_depara` / `usar_api` / `ignorado`.

Banner de alerta no topo da Aba 2 quando há drifts pendentes (badge na navegação também).

## Pipeline de mapping ML

Decisão crítica (01/05/2026): **anúncio ML = SKU pai sempre.** Filhos não têm campanha própria.

### Fluxo

```
FUSION_DePara_Final_v4.xlsx (col 11 "Anuncio ML Fio", col 13 "Anuncio ML Confec")
      │
      ▼
carregar_ml_item_sku_map.py (one-off)
      │  agrega por (item_id, conta) → 1 entry por anúncio (sku_pai)
      │  fonte='depara'
      ▼
ml_item_sku_map (133 mappings DePara cobrindo ~70% items em ads)
      │
      ▼
completar_ml_item_sku_map.py (one-off pós-DePara)
      │  busca items órfãos via /items API + sobe filho→pai
      │  detecta drifts → ml_item_sku_drift
      │  fonte='api_snapshot' (57 mappings)
      ▼
ml_item_sku_map (190 mappings, 100% cobertura ads_metrics)
      │
      ▼
fit_curva_ads.py (cron 09h BRT)
      │  agrega gasto + receita atribuída por (sku_pai, plataforma, dia)
      │  cruza com itens_pedido (resolve filho→pai via produtos.sku_pai)
      │  ajusta fit log da receita E do lucro atribuído
      ▼
ads_curva_otima (12 SKUs pai com fit válido em 02/05)
```

### Drifts iniciais (01/05)

Após promoção pra pai, sobraram **3 drifts pendentes** (de 60 brutos):
- `MLB6132117772`: DePara=`GPDN01`, API=`CMGPD` (erro de cadastro real)
- `MLB3302983703`: DePara=`JQPUF01`, API=`JQPF01` (erro real)
- `MLB3817120847`: DePara=`CLAFEL01`, API=`Agrupado` (ignorado)

## Backfill de ads ML

`backfill_ads.py` permite puxar histórico retroativo via `DATE_FROM/DATE_TO`. **Cap real da API ML: 90 dias retroativos** — não 13 meses como esperado. Tentar `date_from < D-90` retorna `400 "You cannot request metrics with a date greater than 90 days"`. Pra histórico longo, deixar o cron diário rodando e acumular.

Memória: [`feedback_ml_ads_api_cap.md`](~/.claude/projects/-Users-leogusukuma-Documents-PROJETO-MAX/memory/feedback_ml_ads_api_cap.md)

## Limitações conhecidas

1. **Meta + Google Ads não populam `ads_curva_otima` ainda** — esperando credenciais. Quando entrarem em `ads_metrics`, o cron `fit_curva_ads.py` puxa automaticamente (filtro `plataforma` já existe na UI).
2. **Rebate da plataforma** é input manual — schema não tem campo automatizado.
3. **Snapshot não cobre Shopee/Shein/TikTok** — APIs não confirmadas pra produto. Eventos só manuais nesses canais.
4. **Comparação antes/depois usa só pedidos vivos (60d)** — eventos > 30 dias ficam parcialmente cortados na janela `+14d`.
5. **CMV é por SKU pai** — variações de cor/tamanho compartilham o mesmo `produtos.custo_total`. Como o ERP da Fusion sempre tratou.
6. **Cap ML 90d retroativos** — histórico longo só acumula com tempo.
7. **R² do fit varia** — em SKUs com pouco volume, r² < 0.3 é comum. UI sinaliza pra não tratar como recomendação dura.

## Permissionamento

Acesso por `user_roles.dashes` contendo `'simulador'`. RLS:
- `simulacao_cenarios`: usuário só vê seus próprios (4 policies por operação)
- `produto_evento`: leitura aberta a authenticated; insert manual restrito a `criado_por = auth.uid()`
- `ml_item_sku_drift`: leitura aberta; update permitido a authenticated com `resolvido_por = auth.uid()`
- `produtos_snapshot`, `ml_item_sku_map`, `ads_curva_otima`, `canal_custos_faixa`: leitura aberta a authenticated

Liberar acesso:
```sql
UPDATE user_roles SET dashes = array_append(dashes, 'simulador')
WHERE email = '...' AND NOT 'simulador' = ANY(dashes);
```

## Pitfalls técnicos importantes

1. **Canvas wrappers com altura definida:** Chart.js com `responsive + maintainAspectRatio:false` lê do container pai, não do atributo `height`. Sempre `<div style="position:relative; height:Xpx">` em volta.
2. **Lazy render no `<details>`:** o Chart.js inicializa antes do reflow do `<details>` ter calculado tamanho. Usar `requestAnimationFrame` duplo no listener `toggle`.
3. **Botões com `class="tab-btn"` quebram o dash:** o handler global de troca de aba dispara também. Usar `class="seg-btn"` pra controles internos de gráfico.
4. **`STATE.curvaAtual` cache:** `setTimelineMetric` não chama `renderCurva` (recriaria scatter desnecessariamente); usa o cache.
5. **Eixo Y `min: 0`:** receita atribuída ML nunca é negativa; sem isso o Chart.js extrapola pra valores absurdos quando o fit log tem intercepto negativo.
