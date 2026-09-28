// The app's words in five languages (src/i18n): every language has every key English
// has, no more; an entry that changes with a count has forms in every language; every
// language uses the same {placeholders}; nothing is left empty. And no page writes a
// hunter's words straight into its JSX: text, aria-labels, titles and placeholders
// come from the dictionaries, so none stays English in Finnish.
// No browser: node tests/i18n-keys.cjs (esbuild and typescript, which Vite brings).
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path')
const { buildSync } = require('esbuild')
const ts = require('typescript')

const SRC = path.join(__dirname, '..', 'src')
const LANGS = ['en', 'fi', 'sv', 'nb', 'es']
const LOCALES = { en: 'en-GB', fi: 'fi-FI', sv: 'sv-SE', nb: 'nb-NO', es: 'es-ES' }

function load(lang) {
  const out = buildSync({ entryPoints: [path.join(SRC, 'i18n', `${lang}.ts`)], bundle: true, write: false, format: 'cjs', platform: 'node', logLevel: 'silent' })
  const mod = { exports: {} }
  new Function('module', 'exports', 'require', out.outputFiles[0].text)(mod, mod.exports, require)
  return mod.exports.default
}
const dicts = Object.fromEntries(LANGS.map((l) => [l, load(l)]))
const en = dicts.en
const problems = []
const holes = (text) => new Set([...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]))
const forms = (entry) => (typeof entry === 'string' ? [entry] : Object.values(entry))
const allHoles = (entry) => new Set(forms(entry).flatMap((f) => [...holes(f)]))
const same = (a, b) => a.size === b.size && [...a].every((x) => b.has(x))

for (const lang of LANGS) {
  const d = dicts[lang]
  const cats = new Intl.PluralRules(LOCALES[lang]).resolvedOptions().pluralCategories
  for (const key of Object.keys(en)) {
    if (!(key in d)) { problems.push(`${lang}: missing ${key}`); continue }
    const want = en[key], got = d[key]
    if (typeof want !== typeof got) { problems.push(`${lang}: ${key} is ${typeof got}, English is ${typeof want}`); continue }
    if (typeof got === 'object') {
      if (!got.other) problems.push(`${lang}: ${key} has no "other" form`)
      if (cats.includes('one') && !got.one) problems.push(`${lang}: ${key} has no "one" form`)
      for (const f of Object.keys(got)) if (!cats.includes(f)) problems.push(`${lang}: ${key} has a "${f}" form ${lang} doesn't use`)
    }
    if (forms(got).some((f) => typeof f !== 'string' || !f.trim())) problems.push(`${lang}: ${key} is empty`)
    const a = allHoles(want), b = allHoles(got)
    if (!same(a, b)) problems.push(`${lang}: ${key} has {${[...b].join('}, {')}}, English has {${[...a].join('}, {')}}`)
  }
  for (const key of Object.keys(d)) if (!(key in en)) problems.push(`${lang}: ${key} is not an English key`)
}

// ── words written straight into the pages ──
// Text a page may carry as it is: the app's name, units and marks that read the same
// in every language, brand names.
const ALLOWED = new Set(['GameSense', 'Game', 'Sense', 'GameSense v', 'km/h', 'SPYPOINT', 'UBox Pro'])
const TEXT_ATTRS = new Set(['aria-label', 'title', 'placeholder', 'alt', 'label', 'backLabel', 'note', 'summary'])
const words = (s) => { const w = s.replace(/&\w+;/g, ' ').trim(); return /[A-Za-zÀ-ÿ]{2,}/.test(w) && !ALLOWED.has(w) }
// A message rather than a code: a state set to 'edit' or 'activity' is not a sentence,
// 'Saving…' or 'Could not save the stand.' is.
const sentence = (s) => words(s) && (/\s/.test(s.trim()) || /[.…!?:]$/.test(s.trim()))
// The parts of an expression a hunter ends up reading: both answers of a ?:, each side
// of || and ??, what && gives when it holds, both sides of a +, a template's own text.
// Not what goes into a call: t('key'), fmtNumber(n), a helper that picks its own words.
function shown(expr, out = []) {
  if (!expr) return out
  if (ts.isParenthesizedExpression(expr) || ts.isAsExpression(expr) || ts.isNonNullExpression(expr)) return shown(expr.expression, out)
  if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) out.push({ node: expr, text: expr.text })
  else if (ts.isTemplateExpression(expr)) {
    out.push({ node: expr, text: [expr.head.text, ...expr.templateSpans.map((sp) => sp.literal.text)].join(' ') })
  } else if (ts.isConditionalExpression(expr)) { shown(expr.whenTrue, out); shown(expr.whenFalse, out) }
  else if (ts.isBinaryExpression(expr)) {
    const op = expr.operatorToken.kind
    if (op === ts.SyntaxKind.BarBarToken || op === ts.SyntaxKind.QuestionQuestionToken || op === ts.SyntaxKind.PlusToken) { shown(expr.left, out); shown(expr.right, out) }
    else if (op === ts.SyntaxKind.AmpersandAmpersandToken) shown(expr.right, out)
  }
  return out
}
const files = []
const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).forEach((e) => {
  const p = path.join(dir, e.name)
  if (e.isDirectory()) walk(p)
  // The dictionaries themselves are not pages.
  else if (/\.tsx?$/.test(e.name) && !(dir.endsWith('i18n') && LANGS.includes(e.name.replace(/\.ts$/, '')))) files.push(p)
})
walk(SRC)
// The service worker's words are put in it by the build (vite.config.ts).
files.push(path.join(__dirname, '..', 'vite.config.ts'))
const used = new Set(), prefixes = new Set()
for (const file of files) {
  const text = fs.readFileSync(file, 'utf8')
  const rel = path.relative(SRC, file)
  const src = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const at = (node) => `${rel}:${src.getLineAndCharacterOfPosition(node.getStart()).line + 1}`
  // "i18n-ok" on the line, or the one above, says why words there are never a hunter's
  // to read (a crash report's placeholder).
  const lines = text.split('\n')
  const waived = (node) => { const n = src.getLineAndCharacterOfPosition(node.getStart()).line; return /i18n-ok/.test(lines[n] ?? '') || /i18n-ok/.test(lines[n - 1] ?? '') }
  const visit = (node) => {
    if (ts.isJsxText(node) && words(node.text)) problems.push(`${at(node)}: text in JSX: "${node.text.trim().slice(0, 60)}"`)
    if (ts.isJsxAttribute(node) && TEXT_ATTRS.has(node.name.getText()) && node.initializer) {
      const init = node.initializer
      const parts = ts.isStringLiteral(init) ? [{ node: init, text: init.text }] : ts.isJsxExpression(init) ? shown(init.expression) : []
      for (const part of parts) if (words(part.text)) problems.push(`${at(part.node)}: ${node.name.getText()}="${part.text.slice(0, 60)}"`)
    }
    // {'Save'}, {busy ? 'Saving…' : 'Save'}, {err || 'Nothing here yet'}, {`${n} photos`}
    if (ts.isJsxExpression(node) && node.expression && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))) {
      for (const part of shown(node.expression)) if (words(part.text)) problems.push(`${at(part.node)}: text in JSX: "${part.text.slice(0, 60)}"`)
    }
    // A message set straight into a page's state, or thrown for a page to show:
    // setErr('Could not save the stand.'), new Error('No signal').
    const callee = ts.isCallExpression(node) ? node.expression : ts.isNewExpression(node) ? node.expression : null
    const name = callee && (ts.isIdentifier(callee) ? callee.text : ts.isPropertyAccessExpression(callee) ? callee.name.text : '')
    // The build's own refusals (vite.config.ts) are for whoever runs it, not a hunter.
    if (name && !rel.startsWith('..') && (/^set[A-Z]/.test(name) || (ts.isNewExpression(node) && name === 'Error'))) {
      for (const arg of node.arguments ?? []) for (const part of shown(arg)) if (sentence(part.text) && !waived(part.node)) problems.push(`${at(part.node)}: ${name}("${part.text.slice(0, 60)}")`)
    }
    // Keys in use: t('a.b'), and the heads of keys made from data: t(`a.${x}`).
    if (ts.isStringLiteral(node) && node.text in en) used.add(node.text)
    if (ts.isTemplateExpression(node) && /^[\w.]+\.$/.test(node.head.text)) prefixes.add(node.head.text)
    ts.forEachChild(node, visit)
  }
  visit(src)
  // A key named that English doesn't have (the type check catches most; this catches casts).
  for (const m of text.matchAll(/\bt(?:r|n|Or)?\(\s*'([a-zA-Z][\w]*\.[\w.]+)'/g)) {
    if (!(m[1] in en)) problems.push(`${rel}: t('${m[1]}') is not an English key`)
  }
}
const unused = Object.keys(en).filter((k) => !used.has(k) && ![...prefixes].some((p) => k.startsWith(p)))

if (problems.length) {
  console.error(problems.join('\n'))
  assert.fail(`${problems.length} problem(s) with the app's words`)
}
if (unused.length) console.log(`note: ${unused.length} English key(s) not named in src: ${unused.slice(0, 20).join(', ')}${unused.length > 20 ? '…' : ''}`)
console.log(`PASS: ${Object.keys(en).length} keys in ${LANGS.join(', ')}, the same {placeholders} and plural forms in each, and no words written straight into the ${files.length} source files.`)
