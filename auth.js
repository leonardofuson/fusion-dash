// auth.js — Camada de autenticação compartilhada do Fusion BI
// Requer que o SDK do Supabase JS já tenha sido carregado via CDN ANTES deste script.

(function () {
  const SUPABASE_URL = 'https://spulbhnmkomvgohzhfvj.supabase.co';
  const SUPABASE_ANON_KEY =
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNwdWxiaG5ta29tdmdvaHpoZnZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM5NzE5NjQsImV4cCI6MjA4OTU0Nzk2NH0.Ck-7ya2KhWidLoXnIcQRtmb0tJcyjT3EgMIo1LXYUYg';

  if (!window.supabase || !window.supabase.createClient) {
    console.error('[fusionAuth] SDK do Supabase não foi carregado. Inclua https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2 antes de auth.js');
    return;
  }

  const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false,
    },
  });

  // Catálogo de dashes disponíveis (chave → metadados)
  // `cat` agrupa os cards no portal por categoria (cores/seções em index.html): vendas | operacoes | inteligencia | assistente.
  const DASHES = {
    // Vendas
    diario:     { titulo: 'Diário',        descricao: 'Sua foto do dia: vendas por canal, ritmo vs meta e alertas', url: '/diario.html', icone: '☀️', cat: 'vendas' },
    ecommerce:  { titulo: 'E-commerce',    descricao: 'Canais digitais e marketplaces', url: '/ecommerce.html', icone: '🛒', cat: 'vendas' },
    'vendas-historicas': { titulo: 'Vendas Históricas', descricao: 'Histórico mensal do ecommerce: receita, margem e mix por mês', url: '/vendas-historicas.html', icone: '📈', cat: 'vendas' },
    lojas:      { titulo: 'Lojas Físicas', descricao: 'Vendas das lojas físicas (Linx Microvix)', url: '/lojas.html', icone: '🏬', cat: 'vendas' },
    diretoria:  { titulo: 'Diretoria',     descricao: 'Visão executiva consolidada por canal', url: '/diretoria.html', icone: '📊', cat: 'vendas' },
    // Operações
    estoque:    { titulo: 'Estoque',       descricao: 'Posição multi-canal de estoque', url: '/estoque.html', icone: '📦', cat: 'operacoes' },
    compras:    { titulo: 'Compras',       descricao: 'Ordens de compra, produção e fornecedores', url: '/compras-react.html', icone: '🧾', cat: 'operacoes' },
    produtos:   { titulo: 'Produtos',      descricao: 'Base canônica de produtos, de-para universal e grade de medidas (POM)', url: '/produtos.html', icone: '👕', cat: 'operacoes' },
    // Sistema de Estoque (app fusion-estoque-app). Roda EM PARALELO com o dash read-only
    // `estoque` — quem vira a chave do tile é o Leo, depois de conferir a paridade.
    'estoque-sistema': { titulo: 'Estoque (sistema)', descricao: 'Recebimento (entrada com custo), conciliação razão × espelho e a visão de saldo', url: '/estoque-sistema.html', icone: '📦', cat: 'operacoes' },
    financeiro: { titulo: 'Financeiro',    descricao: 'Contas a pagar, fluxo de caixa e DRE de resultado (multi-CNPJ)', url: '/financeiro.html', icone: '💰', cat: 'operacoes' },
    aprovacoes: { titulo: 'Aprovações',    descricao: 'Fila de pagamento: conferência 3 vias e liberação da diretoria', url: '/aprovacoes.html', icone: '✅', cat: 'operacoes' },
    // Inteligência
    simulador:  { titulo: 'Simulador',     descricao: 'Margem por produto + curva ótima de ads', url: '/simulador.html', icone: '🎯', cat: 'inteligencia' },
    crm:        { titulo: 'CRM',           descricao: 'Base 360°, segmentação RFM e histórico de atendimento', url: '/crm.html', icone: '👥', cat: 'inteligencia' },
    marketing:  { titulo: 'Marketing',     descricao: 'Mídia paga Meta + Google: lucro por SKU, MER, auditoria da agência', url: '/marketing.html', icone: '📣', cat: 'inteligencia', restritoPara: ['leonardo@usefusion.com.br', 'allanjonnesj@gmail.com', 'tiago@usefusion.com.br', 'thiago.caleb@usefusion.com.br', 'gabsdev08@gmail.com'] },
    // Assistente
    'max-chat': { titulo: 'Max Chat',      descricao: 'Pergunte sobre vendas, estoque e mais — IA responde na hora', url: 'https://max-chat-frontend.onrender.com', icone: '🤖', cat: 'assistente' },
    'max-chat-admin': { titulo: 'Max Chat — Admin', descricao: 'Qualidade do chat, falhas, sugestões', url: '/max-chat-admin.html', icone: '🛠️', restritoPara: ['leonardo@usefusion.com.br'], cat: 'assistente' },
    // Projetos removido do portal (10/07/2026). Cockpit + Conciliação retirados 08/07/2026 (viraram abas do Financeiro);
    // trafego.html/social.html/loja viraram abas DENTRO do marketing.html (consolidação 08/07).
  };
  // Consolidação no dash Marketing (08/07/2026): dashes standalone viraram abas DENTRO do marketing.html.
  //  - "Tráfego & Atribuição" (trafego.html) → aba "🌐 Funil" (Impressão→Clique→Sessão→Pedido + origens source/medium/link-in-bio).
  //  - "Orgânico" (social.html) → aba "📲 Orgânico" (crescimento, engajamento por formato, melhor horário, top posts).
  // Nota: a performance do Site Próprio (Shopify) virou a aba "🛍️ Loja" DENTRO do dash marketing (marketing.html) — não é mais dash standalone.

  async function getSession() {
    const { data } = await sb.auth.getSession();
    return data.session || null;
  }

  async function getUserRole(session) {
    if (!session) return null;
    const { data, error } = await sb
      .from('user_roles')
      .select('email, nome, role, dashes, ativo')
      .eq('user_id', session.user.id)
      .maybeSingle();
    if (error) {
      console.error('[fusionAuth] erro lendo user_roles:', error);
      return null;
    }
    return data;
  }

  // Garante que existe sessão ativa E (se requiredDash informado) que o usuário tem permissão
  // Retorna {session, role, token, headers} ou null (e redireciona).
  async function requireAuth(requiredDash) {
    const session = await getSession();
    if (!session) {
      window.location.href = '/index.html';
      return null;
    }
    const role = await getUserRole(session);
    if (!role || !role.ativo) {
      alert('Seu usuário não tem permissões cadastradas ou está inativo.');
      await signOut();
      return null;
    }
    if (requiredDash && !role.dashes.includes(requiredDash)) {
      alert('Você não tem permissão para acessar este dashboard.');
      window.location.href = '/index.html';
      return null;
    }
    const headers = {
      apikey: SUPABASE_ANON_KEY,
      Authorization: `Bearer ${session.access_token}`,
    };
    return { session, role, token: session.access_token, headers };
  }

  async function signInWithPassword(email, password) {
    const { data, error } = await sb.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data;
  }

  async function signOut() {
    await sb.auth.signOut();
    window.location.href = '/index.html';
  }

  // API pública
  window.fusionAuth = {
    sb,
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    DASHES,
    getSession,
    getUserRole,
    requireAuth,
    signInWithPassword,
    signOut,
  };
})();
