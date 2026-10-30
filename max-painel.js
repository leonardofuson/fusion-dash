// Max dentro dos sistemas: orbe no canto, que abre uma caixa flutuante. Quem decide se a pessoa usa é o servidor do Max.
// Falha ou recusa: não aparece nada e a tela do sistema segue igual. Nunca bloqueia o sistema de trás.
(function () {
  var APP = 'https://fusion-max.onrender.com';
  var API = 'https://fusion-max-api.onrender.com';
  var script = document.currentScript;
  var sistema = script && script.getAttribute('data-sistema');
  if (!sistema) return;

  function medir(frame, aberto) {
    var celular = window.innerWidth < 640;
    frame.style.width = aberto ? (celular ? '100vw' : '484px') : '76px';
    frame.style.height = aberto ? (celular ? '100dvh' : 'min(684px, 100dvh)') : '76px';
  }

  async function iniciar() {
    var s = (await fusionAuth.sb.auth.getSession()).data.session;
    if (!s) return;
    var r = await fetch(API + '/perfil?sistema=' + encodeURIComponent(sistema), { headers: { Authorization: 'Bearer ' + s.access_token } });
    if (!r.ok) return;
    var frame = document.createElement('iframe');
    frame.title = 'Max';
    frame.allow = 'microphone';
    frame.style.cssText = 'position:fixed;right:0;bottom:0;border:0;background:transparent;z-index:2147483000;color-scheme:normal;';
    medir(frame, false);
    window.addEventListener('message', function (e) {
      if (e.origin !== APP || e.source !== frame.contentWindow || !e.data) return;
      if (e.data.max === 'tamanho') medir(frame, !!e.data.aberto);
      if (e.data.max === 'retirar') frame.remove();
      // O iframe não guarda sessão: pede o token a cada chamada, e esta página cuida de renovar.
      if (e.data.max === 'token') fusionAuth.sb.auth.getSession().then(function (r) {
        frame.contentWindow.postMessage({ max: 'token', id: e.data.id, token: r.data.session ? r.data.session.access_token : null }, APP);
      });
    });
    frame.src = APP + '/painel?sistema=' + encodeURIComponent(sistema);
    document.body.appendChild(frame);
  }
  function quandoPronto() { iniciar().catch(function (e) { console.warn('Max não abriu:', e); }); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', quandoPronto); else quandoPronto();
})();
