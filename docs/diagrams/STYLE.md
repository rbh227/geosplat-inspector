# Diagram style

The diagrams in this repo are built with the [`diagram-design`](https://github.com/cathrynlavery/diagram-design)
Claude Code skill (editorial SVG, one accent colour, 4px grid). Sources live in
`src/` as self-contained HTML; `build.mjs` exports the `.svg` files the README
embeds and assembles the talk deck at `docs/demo/diagrams/index.html`.

```bash
node docs/diagrams/build.mjs
```

## Tokens

The skin is SplatAgent's own: the app's editor palette (`src/index.css`) rebased
onto light paper so the figures read on GitHub in both light and dark theme.

| Role | Value | Where it comes from |
|---|---|---|
| `paper` | `#faf9f7` | warm-neutral light paper |
| `paper-2` | `#f0eeea` | container / secondary fill |
| `ink` | `#1e1e1e` | app `--color-bg-surface` |
| `muted` | `#5d5d5d` | app `--color-text-muted` |
| `soft` | `#7e7e7e` | app `--color-text-dim` |
| `rule` | `rgba(30,30,30,0.12)` | derived from `ink` |
| `accent` | `#5b87c7` | app `--color-accent-cyan` — **1–2 focal elements per diagram** |
| `link` | `#8a6d14` | app `--color-accent-amber`, darkened to hit AA on light paper |

Type: Instrument Serif (titles + italic callouts), Geist (node names), Geist Mono
(technical sublabels). Never mono for human-readable names.

The same table lives in the skill's `references/style-guide.md` under
*Custom tokens — SplatAgent*, so new diagrams inherit it. The skill ships a
skin linter (`scripts/lint-skin.py`); it validates against the skill's *default*
palette, so it flags every colour here by design — its structural checks (no
`<script>`, no external assets, font families) are the useful part.

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
