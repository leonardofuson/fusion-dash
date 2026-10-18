// Confere a sintaxe do JavaScript do fusion-dash (18/10/2026, Fase 4 do framework).
// O dash é HTML puro, sem build: um erro de digitação num <script> só aparece quando a tela
// abre em branco. Aqui cada .js versionado e cada <script> embutido nos .html passa por
// `node --check`. Uso:  node scripts/checar_js.mjs            (todos os arquivos do git)
//                       node scripts/checar_js.mjs --autoteste (prova que sabe reprovar)
import { execFileSync, spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const DIR = mkdtempSync(join(tmpdir(), 'checar-js-'));

// blocos <script> sem src e de tipo executável (ignora JSON, importmap, template)
function blocos(html) {
  const out = [];
  // comentário HTML que cita "<script>" não é bloco: apaga o comentário, mantendo as quebras de linha
  html = html.replace(/<!--[\s\S]*?-->/g, (c) => c.replace(/[^\n]/g, ' '));
  const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html))) {
    const attrs = m[1];
    if (/\bsrc\s*=/i.test(attrs)) continue;
    const tipo = (attrs.match(/\btype\s*=\s*["']?([^"'\s>]+)/i) || [])[1]?.toLowerCase() ?? '';
    if (tipo && !['text/javascript', 'module', 'application/javascript'].includes(tipo)) continue;
    const linha = html.slice(0, m.index).split('\n').length;
    out.push({ codigo: m[2], modulo: tipo === 'module', linha });
  }
  return out;
}

function checar(codigo, modulo, nome) {
  const f = join(DIR, `${nome.replace(/[^\w.-]/g, '_')}.${modulo ? 'mjs' : 'cjs'}`);
  writeFileSync(f, codigo);
  const r = spawnSync(process.execPath, ['--check', f], { encoding: 'utf8' });
  return r.status === 0 ? null : (r.stderr.split('\n').find((l) => /Error/.test(l)) || r.stderr).trim();
}

function rodar(arquivos, ler) {
  let medidos = 0, ruins = 0;
  for (const a of arquivos) {
    const txt = ler(a);
    const lista = a.endsWith('.html') ? blocos(txt) : [{ codigo: txt, modulo: /\.mjs$/.test(a) || /^\s*(import|export)\s/m.test(txt), linha: 1 }];
    for (const b of lista) {
      medidos++;
      const erro = checar(b.codigo, b.modulo, `${a}_${b.linha}`);
      if (erro) { ruins++; console.log(`🔴 ${a} (bloco na linha ${b.linha}): ${erro}`); }
    }
  }
  return { medidos, ruins };
}

if (process.argv.includes('--autoteste')) {
  const casos = {
    'bom.html': ['<script>const a = 1; console.log(a)</script>', 0],
    'ruim.html': ['<p>x</p><script>const a = ;</script>', 1],
    'modulo.html': ['<script type="module">import x from "./x.js"; export const y = x</script>', 0],
    'json.html': ['<script type="application/json">{ não é js }</script>', 0],
    'comentario.html': ['<!-- aqui se fala de <script> ) sem ser código --><p>x</p>', 0],
    'ruim.js': ['function f( {', 1],
  };
  const r = rodar(Object.keys(casos), (a) => casos[a][0]);
  const esperado = Object.values(casos).reduce((s, c) => s + c[1], 0);
  const ok = r.ruins === esperado && r.medidos === 4;
  console.log(ok ? `OK: autoteste (${r.medidos} blocos medidos, ${r.ruins} recusados)` : `🔴 autoteste: medidos ${r.medidos}, recusados ${r.ruins}, esperado 4 e ${esperado}`);
  process.exit(ok ? 0 : 1);
}

const arquivos = execFileSync('git', ['ls-files', '*.html', '*.js', '*.mjs'], { encoding: 'utf8' })
  .split('\n').filter(Boolean).filter((a) => !a.startsWith('node_modules/') && a !== 'scripts/checar_js.mjs');
const r = rodar(arquivos, (a) => readFileSync(a, 'utf8'));
console.log(`${arquivos.length} arquivos, ${r.medidos} blocos de JS medidos, ${r.ruins} com erro`);
process.exit(r.medidos === 0 || r.ruins ? 1 : 0);
