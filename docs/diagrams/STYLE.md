# Diagram style

The diagrams in this repo are built with the [`diagram-design`](https://github.com/cathrynlavery/diagram-design)
Claude Code skill (editorial SVG, one accent colour, 4px grid). Sources live in
`src/` as self-contained HTML; `build.mjs` exports the `.svg` files the README
embeds and assembles the talk deck at `docs/demo/diagrams/index.html`.

```bash
node docs/diagrams/build.mjs
```

## Tokens

The skin **is** the app's editor palette from `src/index.css` — the diagrams are
meant to look like the tool they document.

| Role | Value | App token |
|---|---|---|
| paper | `#151515` | `--color-bg-deep` (viewport backdrop) |
| panel | `#1e1e1e` | `--color-bg-surface` (docked panels) |
| elevated | `#272727` | `--color-bg-elevated` |
| ink | `#d6d6d6` | `--color-text-primary` |
| muted | `#a9a9a9` | `--color-text-secondary` |
| dim | `#7e7e7e` | `--color-text-dim` |
| border | `#383838` / `#2d2d2d` | `--color-border-mid` / `-subtle` |
| accent | `#5b87c7` | `--color-accent-cyan` — **1–2 focal elements per diagram** |
| accent tint | `rgba(91,135,199,0.15)` | `--color-accent-cyan-dim` |

Node radius 4 and 1.5px borders echo the app's near-square, flat chrome.

Type: Instrument Serif (titles + italic asides), Geist (node names, 16px),
Geist Mono (technical sublabels, 12px). The scale is deliberately large — every
figure is meant to survive being projected.

## House rules worth keeping

- One accent colour, at most two accented elements per figure. If three things
  are focal, nothing is.
- Every coordinate, size and gap divisible by 4.
- Orthogonal connectors only — no diagonals; arrow labels sit 6–10px clear of
  their line, on an opaque paper mask.
- ≤9 nodes per diagram. Over that, split into overview + detail.
- Italic Instrument Serif is reserved for editorial callouts (max 2), and a
  callout must never cross an arrow or a node.

## Exported SVG

The exported `.svg` files carry **no webfont `@import`**, on purpose. Two
reasons, and the first one is load-bearing:

1. A standalone SVG is parsed as **XML**, and the Google Fonts URL separates its
   family params with raw `&`. Unescaped, that is a fatal XML parse error —
   GitHub rejects the file with *"Error rendering embedded code · Invalid image
   source"*. Browsers tolerate the same markup inside an HTML page, so the bug is
   invisible if you only ever look at the sources in `src/`. It shipped once
   exactly that way; `build.mjs` now refuses to write an SVG containing an
   unescaped `&`.
2. GitHub blocks external resources in SVG regardless, so the fonts would not
   load even if the file parsed.

So the README figures render in system sans / mono / serif via the fallbacks in
each `font-family`. The layouts are built to hold at those widths. Open the HTML
in `src/` (or the deck) for the real typography.

**When changing the export, validate the artifact, not the source:**

```bash
node docs/diagrams/build.mjs
python3 -c "import xml.etree.ElementTree as ET,glob;[ET.parse(f) for f in glob.glob('docs/diagrams/*.svg')]"
open docs/diagrams/system-overview.svg   # the file GitHub serves, not the HTML
```
