#!/usr/bin/env python3
"""Smoke do dash de Marketing — DIRIGINDO a tela, não fotografando (22/09/2026).

Por que existe: em 22/09 as 9 abas viraram 5 (com sub-chips) e nasceu a aba Mídia. Nenhuma
ferramenta que já tínhamos enxerga isso:
  • `curl` devolve 200 pro HTML inteiro — e devolveria igual com todas as abas quebradas;
  • `smoke_ui.py` só visita ROTAS de app React, e este é um HTML vanilla de uma rota só;
  • `contraste_ui.py` carrega e mede a tela inicial — pane atrás de clique fica fora.
Tudo que esta mudança faz está **atrás de um clique**. Logo, o teste precisa clicar.

Roda contra o ARQUIVO LOCAL (servidor efêmero), então pega regressão ANTES do deploy.
A sessão é injetada no localStorage antes de qualquer script da página — depois do load não
adianta: o requireAuth já rodou e já redirecionou.

  .venv/bin/python fusion-dash/scripts/smoke_marketing.py
  .venv/bin/python fusion-dash/scripts/smoke_marketing.py --autoteste   # prova que sabe reprovar
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DASH = RAIZ / "fusion-dash"
sys.path.insert(0, str(RAIZ / "scripts"))
from chrome_cdp import Navegador  # noqa: E402

PORTA = 8899
PROJ = "spulbhnmkomvgohzhfvj"

# (aba, pane, seletor do que TEM que estar pintado, é pintado por JS?)
#
# ⚠️ O seletor é a parte frágil do teste, e errar nele dá VERDE FALSO, não vermelho. Duas
# armadilhas pegas ao escrever isto (22/09): `#sh-kpis` não existe (é `sh-kpis-loja`) e
# `#kpis-organico` não existe (é `org-kpis`) — o segundo passava porque eu tinha deixado um
# fallback `#pane-organico .card`, que casa com markup ESTÁTICO e aprovaria a tela mesmo se o
# JS nunca rodasse. Por isso: um seletor por tela, sem fallback, e a coluna `dinamico` separa
# "o JS pintou" de "o HTML estava lá desde sempre".
# Conferir que todo seletor existe:  grep -c 'id="org-kpis"' marketing.html
TELAS = [
    ("dinheiro", "geral",     "#kpis-geral .kpi",            True),
    ("midia",    "midia",     "#kpis-midia .kpi",            True),
    ("midia",    "criativo",  "#kpis-criativo .kpi",         True),
    ("midia",    "funil",     "#fn-kpis .kpi",               True),
    ("midia",    "incr",      "#pane-incr .filtros input",   False),  # medir exige clicar
    ("midia",    "audit",     "#kpis-audit .kpi",            True),
    ("loja",     "shopify",   "#sh-kpis-loja .kpi",          True),
    ("loja",     "sku",       "#kpis-sku .kpi",              True),
    ("organico", "organico",  "#org-kpis .kpi",              True),
    ("analista", "analista",  "#pane-analista .filtros button", False),  # analisar exige clicar
]
# link antigo (de quando eram 9 abas) -> onde tem que chegar agora
LEGADO = {"criativo": "midia", "funil": "midia", "incr": "midia", "audit": "midia",
          "shopify": "loja", "sku": "loja", "geral": "dinheiro", "organico": "organico"}


def env():
    e = {}
    for linha in (RAIZ / ".env").read_text().splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            e[k] = v.strip().strip('"').strip("'")
    return e


def anon():
    m = re.search(r"SUPABASE_ANON_KEY\s*=\s*['\"]([^'\"]+)", (DASH / "auth.js").read_text())
    if not m:
        sys.exit("🔴 não achei a anon key em auth.js")
    return m.group(1)


def entrar(url, key, email, senha):
    req = urllib.request.Request(
        f"{url}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": senha}).encode(),
        headers={"apikey": key, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pre_js(sessao):
    """Injeta a sessão no formato que o supabase-js v2 espera ler do localStorage."""
    dados = {"access_token": sessao["access_token"], "refresh_token": sessao["refresh_token"],
             "expires_at": int(time.time()) + int(sessao.get("expires_in", 3600)),
             "expires_in": int(sessao.get("expires_in", 3600)),
             "token_type": "bearer", "user": sessao.get("user", {})}
    return (f"try{{localStorage.setItem('sb-{PROJ}-auth-token', {json.dumps(json.dumps(dados))});}}"
            "catch(e){}")


def main():
    autoteste = "--autoteste" in sys.argv
    e = env()
    if not e.get("FUSION_TEST_EMAIL"):
        sys.exit("🔴 FUSION_TEST_EMAIL/FUSION_TEST_PASSWORD faltam no .env — sem login não há teste.")
    key = anon()
    sessao = entrar(e["SUPABASE_URL"], key, e["FUSION_TEST_EMAIL"], e["FUSION_TEST_PASSWORD"])
    print(f"login ok — {e['FUSION_TEST_EMAIL']}")

    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(PORTA)], cwd=DASH,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.2)
    base = f"http://localhost:{PORTA}/marketing.html"
    ok = bad = 0
    try:
        with Navegador() as nav:
            # ── 1. as 10 telas, clicando aba e sub-chip como a pessoa clica
            passos = []
            for aba, pane, sel, _din in TELAS:
                passos += [
                    ("js", f"document.querySelector('.tab[data-t=\"{aba}\"]').click()"),
                    ("pausa", 0.6),
                    ("js", f"(function(){{var b=document.querySelector('.subchip[data-p=\"{pane}\"]');"
                           f"if(b)b.click();return !!b}})()"),
                    # ESPERA ATÉ APARECER (prazo 12s), não fotografa num instante fixo: o pane
                    # busca dado ao abrir, e medir antes do fetch voltar reprova tela sadia.
                    # O prazo é o que mantém o teste honesto — não espera pra sempre.
                    ("js", "(async()=>{const t0=Date.now();"
                           f"const sel={json.dumps(sel)};"
                           "while(Date.now()-t0<12000){"
                           "  if(document.querySelectorAll(sel).length)break;"
                           "  await new Promise(r=>setTimeout(r,200));}"
                           "return JSON.stringify({pane:(document.querySelector('.pane.on')||{}).id,"
                           "vivo:document.querySelectorAll(sel).length,ms:Date.now()-t0,"
                           "txt:((document.querySelector('.pane.on')||{}).innerText||'').slice(0,60)})})()"),
                ]
            # ── 2. links antigos continuam levando ao lugar certo
            for velho in LEGADO:
                passos += [("js", f"location.hash='#{velho}';"), ("pausa", 0.8),
                           ("js", "JSON.stringify({aba:(document.querySelector('.tab.on')||{}).dataset,"
                                  "pane:(document.querySelector('.pane.on')||{}).id,"
                                  "aviso:document.getElementById('rota-aviso').style.display})")]
            # ── 3. hash inexistente AVISA (não finge que era ali)
            passos += [("js", "location.hash='#inventada';"), ("pausa", 0.8),
                       ("js", "JSON.stringify({aviso:document.getElementById('rota-aviso').style.display,"
                              "pane:(document.querySelector('.pane.on')||{}).id})")]
            # ── 4. hash de auth NÃO pode virar alarme falso
            passos += [("js", "location.hash='#access_token=abc&refresh_token=def';"), ("pausa", 0.8),
                       ("js", "JSON.stringify({aviso:document.getElementById('rota-aviso').style.display})")]
            # ── 5. a busca da Mídia casa NOME e CÓDIGO na mesma caixa, fora de ordem, sem acento
            def digitar(txt):
                return ("js", "(()=>{const i=document.getElementById('md-busca');"
                              f"i.value={json.dumps(txt)};"
                              "i.dispatchEvent(new Event('input',{bubbles:true}));"
                              "return JSON.stringify({n:document.querySelectorAll('#tb-midia tr').length,"
                              "primeiro:(document.querySelector('#tb-midia .md-nome .t')||{}).innerText||'',"
                              "vazio:(document.querySelector('#tb-midia td.muted')||{}).innerText||''})})()")
            passos += [
                ("js", "location.hash='#midia/midia'"), ("pausa", 3.0),
                # termo em CAIXA ALTA e sem acento tem que achar o nome com acento/minúscula;
                # e duas palavras fora de ordem têm que casar (é a regra do CLAUDE.md)
                ("js", "JSON.stringify({total:document.querySelectorAll('#tb-midia tr').length,"
                       "nomes:[...document.querySelectorAll('#tb-midia .md-nome .t')].map(x=>x.innerText).slice(0,9)})"),
                digitar("compra abo"),      # fora de ordem
                digitar("COMPRA"),          # caixa alta
                digitar("zzzznaoexiste"),   # vazio tem que EXPLICAR
                digitar(""),                # limpar volta tudo
            ]
            # ── 6. RECONCILIAÇÃO: os números da tela têm que bater entre si.
            # (a) a receita do gráfico novo × o KPI "Receita Site" da mesma tela — é o teste que
            #     pega a armadilha do rev_site (valor_bruto cru, com frete, sem filtrar status);
            # (b) o total da tabela de campanhas × o KPI "Gasto Meta".
            passos += [
                ("js", "document.querySelector('.tab[data-t=\"dinheiro\"]').click()"), ("pausa", 1.5),
                ("js", "(()=>{const K=kpiSet(STATE.mer,STATE.canal,STATE.trafego);"
                       "const c=CHARTS['ch-combo'];"
                       "const rec=c?c.data.datasets[0].data.reduce((a,b)=>a+(+b||0),0):null;"
                       "const inv=c?c.data.datasets[1].data.reduce((a,b)=>a+(+b||0),0):null;"
                       "return JSON.stringify({kpiRec:Math.round(K.rec),grafRec:rec,"
                       "kpiMeta:Math.round(K.meta),grafInv:inv,"
                       "dias:c?c.data.labels.length:0})})()"),
                ("js", "location.hash='#midia/midia'"), ("pausa", 2.0),
                ("js", "(()=>{const K=kpiSet(STATE.mer,STATE.canal,STATE.trafego);"
                       "const t=[...document.querySelectorAll('#tf-midia td')].map(x=>x.innerText);"
                       "const n=s=>+(String(s||'').replace(/[^0-9,-]/g,'').replace(',','.'))||0;"
                       "return JSON.stringify({kpiMeta:Math.round(K.meta),tabela:n(t[9]),"
                       "frescor:(document.getElementById('md-frescor')||{}).innerText||''})})()"),
            ]
            r = nav.dirigir(base, passos, espera=9.0, pre_js=pre_js(sessao))

        res = r["resultados"]
        print("\n── telas (5 abas · 10 panes) " + "─" * 30)
        i = 0
        for aba, pane, sel, din in TELAS:
            # 4 passos por tela: clique na aba · pausa · clique no sub-chip · leitura com prazo
            i += 2
            teve_chip = res[i]; i += 1
            d = json.loads(res[i] or "{}"); i += 1
            certo = d.get("pane") == "pane-" + pane
            vivo = d.get("vivo", 0)
            if certo and vivo > 0:
                ok += 1
                marca = "" if din else " (estático)"
                print(f"  ✅ {aba}/{pane:9} {vivo:3} elementos em {d.get('ms',0)/1000:.1f}s{marca} · {d.get('txt','')[:34].strip()}")
            else:
                bad += 1
                print(f"  🔴 {aba}/{pane:9} pane={d.get('pane')} elementos={vivo} (esperou {d.get('ms',0)/1000:.0f}s)")

        print("\n── links antigos (#criativo, #sku…) " + "─" * 22)
        for velho, aba_certa in LEGADO.items():
            i += 1                      # o set do hash
            i += 1                      # a pausa
            d = json.loads(res[i] or "{}")
            i += 1
            chegou = (d.get("aba") or {}).get("t")
            if chegou == aba_certa and d.get("pane") == "pane-" + velho:
                ok += 1
                print(f"  ✅ #{velho:9} → {aba_certa}/{velho}")
            else:
                bad += 1
                print(f"  🔴 #{velho:9} → aba={chegou} pane={d.get('pane')} (esperado {aba_certa}/{velho})")

        i += 2
        d = json.loads(res[i] or "{}"); i += 1
        if d.get("aviso") == "block":
            ok += 1; print("\n  ✅ #inventada avisa que a tela não existe (não finge que era ali)")
        else:
            bad += 1; print(f"\n  🔴 #inventada NÃO avisou (display={d.get('aviso')})")

        i += 2
        d = json.loads(res[i] or "{}"); i += 1
        if d.get("aviso") != "block":
            ok += 1; print("  ✅ #access_token=… não vira alarme falso")
        else:
            bad += 1; print("  🔴 #access_token=… disparou o aviso de rota inexistente")

        i += 2                                   # hash + pausa
        base_d = json.loads(res[i] or "{}"); i += 1
        total = base_d.get("total", 0)
        if total > 0:
            ok += 1
            print(f"\n  ✅ tabela de mídia com {total} campanha(s) · 1ª: {(base_d.get('nomes') or [''])[0][:38]}")
        else:
            bad += 1; print("\n  🔴 tabela de mídia vazia")

        print("\n── busca (nome e código na mesma caixa) " + "─" * 18)
        fora  = json.loads(res[i] or "{}"); i += 1
        alta  = json.loads(res[i] or "{}"); i += 1
        nada  = json.loads(res[i] or "{}"); i += 1
        limpa = json.loads(res[i] or "{}"); i += 1
        for rotulo, d, cond, detalhe in [
            ("'compra abo' (fora de ordem)", fora,  fora.get("n", 0) > 0 and fora.get("n", 99) < total,
             f"{fora.get('n')} de {total} · {fora.get('primeiro','')[:34]}"),
            ("'COMPRA' (caixa alta)",        alta,  alta.get("n", 0) > 0,
             f"{alta.get('n')} de {total}"),
            ("termo inexistente EXPLICA",    nada,  "casa com" in (nada.get("vazio") or ""),
             (nada.get("vazio") or "(vazio mudo)")[:52]),
            ("limpar volta tudo",            limpa, limpa.get("n") == total,
             f"{limpa.get('n')} de {total}"),
        ]:
            if cond:
                ok += 1; print(f"  ✅ {rotulo}: {detalhe}")
            else:
                bad += 1; print(f"  🔴 {rotulo}: {detalhe}")

        print("\n── reconciliação (os números batem entre si?) " + "─" * 12)
        i += 2                                   # clique na aba Dinheiro + pausa
        g = json.loads(res[i] or "{}"); i += 1
        i += 2                                   # hash Mídia + pausa
        t = json.loads(res[i] or "{}"); i += 1
        # tolerância = 1 centavo por dia: o gráfico arredonda CADA dia (Math.round), então a soma
        # não pode ser exigida ao centavo. Acima disso não é arredondamento, é fonte errada.
        tol = max(2, g.get("dias", 0))
        for rotulo, a, b, nota in [
            ("receita do gráfico × KPI Receita Site", g.get("grafRec"), g.get("kpiRec"),
             "se divergir, o gráfico voltou a ler rev_site (valor_bruto cru)"),
            ("investimento do gráfico × KPI Gasto Meta", g.get("grafInv"), g.get("kpiMeta"), ""),
        ]:
            if a is None or b is None:
                bad += 1; print(f"  🔴 {rotulo}: não deu pra medir (a={a} b={b})")
            elif abs(a - b) <= tol:
                ok += 1; print(f"  ✅ {rotulo}: {a:,.0f} ≈ {b:,.0f}".replace(",", "."))
            else:
                bad += 1
                print(f"  🔴 {rotulo}: {a:,.0f} × {b:,.0f} (diferença {abs(a-b):,.0f}) {nota}".replace(",", "."))

        # A tabela de mídia lê as views VIVAS e o KPI lê a MV do cron: durante o dia elas
        # DIVERGEM por construção. Exigir igualdade aqui seria exigir que o dashboard mentisse.
        # O que se exige é HONESTIDADE: divergiu, a tela tem que declarar a defasagem.
        dif = abs((t.get("tabela") or 0) - (t.get("kpiMeta") or 0))
        declara = "a mais que a aba Dinheiro" in (t.get("frescor") or "")
        if dif <= tol:
            ok += 1; print(f"  ✅ tabela de campanhas × KPI Gasto Meta: {t.get('tabela'):,.0f} ≈ {t.get('kpiMeta'):,.0f}".replace(",", "."))
        elif declara:
            ok += 1
            print(f"  ✅ tabela × KPI difere em {dif:,.0f} (dado vivo × MV do cron) — e a tela DECLARA".replace(",", "."))
        else:
            bad += 1
            print(f"  🔴 tabela × KPI difere em {dif:,.0f} e a tela NÃO declara a defasagem".replace(",", "."))

        graves = [x for x in r["erros"] if "favicon" not in x and "404" not in x]
        if graves:
            print(f"\n  ⚠️  console.error ({len(graves)}):")
            for g in graves[:5]:
                print("      " + g[:150])

        # ⛔ zero tela medida sai 🔴, nunca ✅ — instrumento que não mediu não pode aprovar (#007)
        if ok == 0:
            print("\n🔴 NENHUMA tela medida — o teste não rodou, não é que passou.")
            return 1
        print(f"\n{'🔴' if bad else '✅'} {ok} ok · {bad} falhas")
        if autoteste:
            print("\n── autoteste: a régua sabe reprovar? " + "─" * 20)
            with Navegador() as nav2:
                r2 = nav2.dirigir(base, [("js", "JSON.stringify({pane:(document.querySelector('.pane.on')||{}).id})")],
                                  espera=6.0)   # SEM sessão: tem que cair no login
                d2 = json.loads(r2["resultados"][0] or "{}")
                print("  ✅ sem sessão o dash não abre (reprova corretamente)"
                      if d2.get("pane") in (None, "") else
                      f"  🔴 sem sessão ainda abriu o pane {d2.get('pane')}")
        return 1 if bad else 0
    finally:
        srv.terminate()


if __name__ == "__main__":
    sys.exit(main())
