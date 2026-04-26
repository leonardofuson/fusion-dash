# fusion-dash — Portal BI

> Dashboards de **consumo** de dados. Schema do Supabase em [SCHEMA.md](../SCHEMA.md). Dash **Compras** (sistema de input de OC/OP, fundamentalmente diferente) em [COMPRAS.md](COMPRAS.md).

## Arquitetura

- Login via Supabase Auth → JWT → PostgREST com RLS
- Catálogo de dashes hardcoded em `auth.js` (objeto `DASHES`)
- Cada dash usa `fusionAuth.requireAuth('key')` como gate
- Dashes ativos: `lojas`, `ecommerce`, `diretoria`, `estoque`, `financeiro`, `compras`
- Padrão de fetch: paralelo de `pedidos` + `pedidos_historico` com `.concat()` no cliente
- RLS em tudo (`pedidos`, `pedidos_historico`, `produtos`, `estoque`, `contas_pagar`, `user_roles`, `metas_lojas`) — sem login = sem dado

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

Pra criar um novo dash (ex: `marketing`):
1. Editar `auth.js` — adicionar entry no objeto `DASHES`:
   ```js
   marketing: { titulo: 'Marketing', descricao: 'Campanhas e CAC', url: '/marketing.html', icone: '📣' }
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
- **Pedidos**: fetch paralelo de `pedidos` + `pedidos_historico` com `.concat()`. Sempre filtrar `status NOT IN ('cancelado', 'devolvido')` em receita.
- **Mobile**: breakpoint principal 768px. Cards empilhados em mobile, lado-a-lado em desktop.
- **Export PNG**: html2canvas. Aplicar em todo card de KPI relevante.

---

## Dash Lojas (`lojas.html`) — v3 (deploy 17/04/2026)

Fonte: `pedidos` + `pedidos_historico` (origem_conta=kwid). Atacado/flecha excluído via `IGNORAR_LOJA`.

**Conceitos-chave para código:**
- Filtros persistentes na URL (`?de=...&ate=...&p=30d&lojas=...`)
- `lojaDisplay()` = identity (desde 23/04/2026). Nomes curtos são fonte da verdade na base. `LOJA_CORES` usa keys sem prefixo.
- Fotos vendedores: `vendedores/{primeiro-nome}.jpg` (lowercase, sem acento). `avatarHtml()` tenta `{primeiro-segundo}.jpg` → `{primeiro}.jpg` → iniciais.
- Metas: fetch de `metas_lojas` uma vez por sessão (`STATE.metasLoaded`). Sem meta = fallback gracioso.
- Projeção do mês: média por DOW dos dias observados, fallback pra média diária. Ativa quando range inclui hoje.
- Charts: registro em `CHARTS`. Sparklines em `CHARTS.lojaSparklines[]`.
- Cross-filtering bidirecional: click vendedor ↔ click SKU.
- Categorias excluídas: TECIDO, TROCA.

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
- Whitelist fabricação própria (`SKU_FINALIZADOS`, 19 SKUs): `CLAFEL01, CLAF01, CLAJUSTE, CLTECH, CLMALHA, CLSJ01, CLMC01, CLOX01, CMBB, CMINDIANO, CMMC, CMEL01, CMLS01, CMPL01, CMGPD, SJPREMIUM, TNMC01, TNPV01, TNPVAJ`.
- **Pipeline de custo**: dash consome `produtos.custo_total`. Pipeline completo (RPC `recalcular_custos_sku`, `custos_sku`) em [../fusion-sync/MRP.md](../fusion-sync/MRP.md).
- Aba **Insumos** é stub (não implementada).
- Render CLI disponível (`render login` se token expirar, `render jobs create` para disparar syncs).

## Dash Ecommerce (`ecommerce.html`)

- Fonte: `pedidos` + `pedidos_historico` (excluindo lojas físicas e atacado).
- **Custos por canal**: tabela `CANAL_CUSTO` hardcoded. Fonte da verdade: [../CUSTOS_POR_CANAL.md](../CUSTOS_POR_CANAL.md).
- Margem líquida = receita − (receita × custo_canal%) − Σ(qty × `produtos.custo_total`).

## Dash Diretoria (`diretoria.html`)

- Visão consolidada (todos os canais). Receita, top SKUs, anomalias.
- **Pendência**: refatorar pra usar `vw_pedidos_completo` em vez de fetch paralelo.
