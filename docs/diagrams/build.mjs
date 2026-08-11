// Build the repo's diagrams from their HTML sources.
//
//   node docs/diagrams/build.mjs
//
// Sources of truth are the self-contained pages in docs/diagrams/src/ — editorial
// SVG built with the `diagram-design` skill (see docs/diagrams/STYLE.md for the
// SplatAgent token set). This script does two things and nothing else:
//
//   1. Extracts each page's <svg> into docs/diagrams/<name>.svg for the README.
//      (GitHub renders these inline; it won't fetch the webfonts, so the SVGs
//      fall back to system sans / mono / serif. Open the HTML for the real type.)
//   2. Assembles the talk deck at docs/demo/diagrams/index.html — one file, no
//      JS, CSS-only tabs, in presentation order.
//
// No dependencies. Deterministic: same sources in, same bytes out.

import { readFileSync, writeFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, 'src')
const DECK_OUT = join(HERE, '..', 'demo', 'diagrams', 'index.html')

const FONTS =
  "@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1" +
  "&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap');"

// Which diagrams the talk uses, in the order they are spoken.
const DECK = [
  ['splat-anatomy',     'Splats'],
  ['sfm-colmap',        'COLMAP'],
  ['pipeline',          'Pipeline'],
  ['system-overview',   'The app'],
  ['agent-stages',      'Two agents'],
  ['agent-analyst',     'Analyst'],
  ['agent-cleanup',     'Cleaner'],
]

function read(name) {
  const html = readFileSync(join(SRC, `${name}.html`), 'utf8')
  const svg = html.match(/<svg[\s\S]*?<\/svg>/)
  if (!svg) throw new Error(`no <svg> in ${name}.html`)
  const eyebrow = html.match(/<p class="eyebrow">([\s\S]*?)<\/p>/)
  const title = html.match(/<h1>([\s\S]*?)<\/h1>/)
  return {
    name,
    svg: svg[0],
    eyebrow: eyebrow ? eyebrow[1].trim() : '',
    title: title ? title[1].trim() : name,
  }
}

// Standalone .svg for the README.
//
// Deliberately NO webfont @import. A standalone SVG is parsed as XML, and the
// Google Fonts URL carries raw `&` between its family params — unescaped, that
// is a fatal XML parse error and GitHub rejects the file with "Invalid image
// source". Escaping it would be legal but pointless: GitHub blocks external
// resources in SVG anyway, so the fonts would never load. The font-family
// attributes keep their generic fallbacks (system sans / mono / serif); open
// the HTML source or the deck to see the real typography.
//
// Explicit width/height are added alongside viewBox so consumers that ignore
// viewBox still size the image correctly.
function standalone(svg) {
  const box = svg.match(/viewBox="0 0 (\d+) (\d+)"/)
  if (!box) throw new Error('svg has no "0 0 W H" viewBox')
  return `${svg.replace(/^<svg /, `<svg width="${box[1]}" height="${box[2]}" `)}\n`
}

// Guard the class of bug that shipped once: an artifact that renders in a
// browser (as HTML) but is not well-formed XML, so every strict SVG consumer —
// GitHub included — refuses it. Node has no XML parser; an unescaped `&` is the
// failure mode that actually bites, so check for it directly.
function assertXmlSafe(name, svg) {
  const bad = svg.match(/&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/)
  if (bad) {
    const at = svg.slice(bad.index, bad.index + 40).replace(/\n/g, ' ')
    throw new Error(`${name}.svg: unescaped "&" makes this invalid XML — near: ${at}`)
  }
  if (!svg.startsWith('<svg ') || !svg.trimEnd().endsWith('</svg>')) {
    throw new Error(`${name}.svg: does not start with <svg and end with </svg>`)
  }
}

const names = readdirSync(SRC)
  .filter((f) => f.endsWith('.html'))
  .map((f) => f.replace(/\.html$/, ''))
  .sort()

const pages = new Map(names.map((n) => [n, read(n)]))

for (const [name, page] of pages) {
  const svg = standalone(page.svg)
  assertXmlSafe(name, svg)
  writeFileSync(join(HERE, `${name}.svg`), svg)
}

const tabs = DECK.map(([name, label], i) => {
  const page = pages.get(name)
  if (!page) throw new Error(`deck references a missing diagram: ${name}`)
  return { ...page, label, i }
})

const deck = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SplatAgent — talk diagrams</title>
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --color-paper:  #151515;
      --color-panel:  #1e1e1e;
      --color-ink:    #d6d6d6;
      --color-muted:  #a9a9a9;
      --color-dim:    #7e7e7e;
      --color-accent: #5b87c7;
      --font-sans:    'Geist', system-ui, sans-serif;
      --font-serif:   'Instrument Serif', serif;
      --font-mono:    'Geist Mono', ui-monospace, monospace;
    }
    body {
      font-family: var(--font-sans);
      background: var(--color-paper);
      color: var(--color-ink);
      padding: 2.5rem 2rem 4rem;
    }
    .frame { max-width: 1200px; margin: 0 auto; }
    input[name="tab"] { position: absolute; opacity: 0; pointer-events: none; }
    nav {
      display: flex; flex-wrap: wrap; gap: 0.5rem;
      border-bottom: 1px solid rgba(214,214,214,0.12);
      padding-bottom: 0.75rem; margin-bottom: 2rem;
    }
    nav label {
      font-family: var(--font-mono); font-size: 0.66rem; font-weight: 500;
      letter-spacing: 0.14em; text-transform: uppercase;
      color: var(--color-dim); cursor: pointer;
      padding: 0.4rem 0.8rem; border: 1px solid #383838;
      border-radius: 4px; background: var(--color-panel);
    }
    nav label span { color: #5d5d5d; margin-right: 0.4rem; }
    nav label:hover { border-color: #474747; color: var(--color-muted); }
    section { display: none; }
    .eyebrow {
      font-family: var(--font-mono); font-size: 0.7rem; font-weight: 500;
      letter-spacing: 0.18em; text-transform: uppercase;
      color: var(--color-dim); margin-bottom: 0.5rem;
    }
    h1 {
      font-family: var(--font-serif);
      font-size: clamp(1.5rem, 2.4vw + 0.75rem, 2rem);
      font-weight: 400; letter-spacing: -0.02em; line-height: 1.15;
      margin-bottom: 1.5rem;
    }
    .scroll { overflow-x: auto; }
    svg { width: 100%; min-width: 900px; display: block; }
${tabs
  .map(
    (t) => `    #t${t.i}:checked ~ nav label[for="t${t.i}"] {
      color: var(--color-accent); border-color: var(--color-accent);
      background: rgba(91,135,199,0.15);
    }
    #t${t.i}:checked ~ main #p${t.i} { display: block; }`
  )
  .join('\n')}
    @media print {
      nav { display: none; }
      section { display: block !important; page-break-after: always; }
      svg { min-width: 0; }
    }
  </style>
</head>
<body>
  <div class="frame">
${tabs
  .map((t) => `    <input type="radio" name="tab" id="t${t.i}"${t.i === 0 ? ' checked' : ''}>`)
  .join('\n')}

    <nav>
${tabs
  .map(
    (t) =>
      `      <label for="t${t.i}"><span>${String(t.i + 1).padStart(2, '0')}</span>${t.label}</label>`
  )
  .join('\n')}
    </nav>

    <main>
${tabs
  .map(
    (t) => `      <section id="p${t.i}">
        <p class="eyebrow">${t.eyebrow}</p>
        <h1>${t.title}</h1>
        <div class="scroll">
        ${t.svg.split('\n').join('\n        ')}
        </div>
      </section>`
  )
  .join('\n')}
    </main>
  </div>
</body>
</html>
`

writeFileSync(DECK_OUT, deck)

console.log(`wrote ${pages.size} svg + deck (${tabs.length} tabs)`)
for (const n of names) console.log(`  docs/diagrams/${n}.svg`)
console.log('  docs/demo/diagrams/index.html')
