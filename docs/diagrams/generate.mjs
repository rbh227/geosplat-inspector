// Hand-drawn-style SVG diagram generator for the README.
// No dependencies. Regenerate with:  node docs/diagrams/generate.mjs
// Jitter is seeded, so output is deterministic and diff-friendly.

import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const OUT = dirname(fileURLToPath(import.meta.url))

const PAPER = '#fdf9ef'
const EDGE = '#c9c0ac'
const INK = '#2d2a26'
const SOFT = '#6f6a60'
const BLUE = '#1971c2'
const GREEN = '#2f9e44'
const ORANGE = '#e8590c'
const VIOLET = '#9c36b5'
const RED = '#e03131'
const GRAY = '#868e96'
const FONT = "'Segoe Print','Bradley Hand','Comic Sans MS','Comic Neue',cursive"

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

class Sketch {
  constructor(name, w, h, seed, title) {
    this.name = name; this.w = w; this.h = h
    this.r = mulberry32(seed)
    this.el = []
    this.el.push(`<rect x="3" y="3" width="${w - 6}" height="${h - 6}" rx="18" fill="${PAPER}"/>`)
    this.rectS(12, 12, w - 24, h - 24, { color: EDGE, width: 2, plainFill: false })
    if (title) this.text(38, 58, title, { size: 25, color: INK })
  }

  j(a) { return (this.r() * 2 - 1) * a }

  smooth(pts) {
    let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`
    for (let i = 1; i < pts.length - 1; i++) {
      const mx = (pts[i][0] + pts[i + 1][0]) / 2
      const my = (pts[i][1] + pts[i + 1][1]) / 2
      d += ` Q ${pts[i][0].toFixed(1)} ${pts[i][1].toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`
    }
    const l = pts[pts.length - 1]
    d += ` L ${l[0].toFixed(1)} ${l[1].toFixed(1)}`
    return d
  }

  sample(x1, y1, x2, y2, bend = 0, jit = 2) {
    const len = Math.max(1, Math.hypot(x2 - x1, y2 - y1))
    const n = Math.max(3, Math.ceil(len / 55))
    const nx = -(y2 - y1) / len, ny = (x2 - x1) / len
    const pts = []
    for (let i = 0; i <= n; i++) {
      const t = i / n
      let x = x1 + (x2 - x1) * t, y = y1 + (y2 - y1) * t
      const b = bend * 4 * t * (1 - t)
      x += nx * b; y += ny * b
      if (i > 0 && i < n) { x += this.j(jit); y += this.j(jit) }
      pts.push([x, y])
    }
    return pts
  }

  stroke(d, { color = INK, width = 2, dash, opacity = 0.95 } = {}) {
    this.el.push(`<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"${dash ? ` stroke-dasharray="${dash}"` : ''} opacity="${opacity}"/>`)
  }

  line(x1, y1, x2, y2, o = {}) {
    this.stroke(this.smooth(this.sample(x1, y1, x2, y2, o.bend || 0)), o)
    this.stroke(this.smooth(this.sample(x1, y1, x2, y2, o.bend || 0)), { ...o, width: (o.width || 2) * 0.75, opacity: 0.4 })
  }

  rectS(x, y, w, h, o = {}) {
    const { fill, fillOpacity = 0.10, plainFill = true } = o
    if (fill && plainFill) this.el.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="${fill}" opacity="${fillOpacity}"/>`)
    const v = 3
    this.line(x - v, y + this.j(2), x + w + v, y + this.j(2), o)
    this.line(x + w + this.j(2), y - v, x + w + this.j(2), y + h + v, o)
    this.line(x + w + v, y + h + this.j(2), x - v, y + h + this.j(2), o)
    this.line(x + this.j(2), y + h + v, x + this.j(2), y - v, o)
  }

  ellipseS(cx, cy, rx, ry, o = {}) {
    for (let pass = 0; pass < 2; pass++) {
      const pts = []
      const n = 26
      const start = this.r() * Math.PI * 2
      for (let i = 0; i <= n; i++) {
        const a = start + (i / n) * Math.PI * 2
        pts.push([cx + Math.cos(a) * rx + this.j(2.5), cy + Math.sin(a) * ry + this.j(2.5)])
      }
      this.stroke(this.smooth(pts), { ...o, width: pass ? (o.width || 2) * 0.75 : o.width, opacity: pass ? 0.4 : (o.opacity ?? 0.95) })
    }
  }

  arrow(x1, y1, x2, y2, o = {}) {
    this.line(x1, y1, x2, y2, o)
    const bend = o.bend || 0
    // tangent near the tip of the (possibly bent) curve
    const t = 0.94
    const len = Math.max(1, Math.hypot(x2 - x1, y2 - y1))
    const nx = -(y2 - y1) / len, ny = (x2 - x1) / len
    const bt = bend * 4 * t * (1 - t)
    const px = x1 + (x2 - x1) * t + nx * bt
    const py = y1 + (y2 - y1) * t + ny * bt
    const ang = Math.atan2(y2 - py, x2 - px)
    for (const da of [0.5, -0.5]) {
      const hx = x2 - Math.cos(ang + da) * 13
      const hy = y2 - Math.sin(ang + da) * 13
      this.line(x2, y2, hx, hy, { color: o.color, width: o.width, dash: undefined })
    }
  }

  text(x, y, lines, { size = 15, color = INK, anchor = 'start', lh = 1.45, weight } = {}) {
    const arr = Array.isArray(lines) ? lines : [lines]
    const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    const tspans = arr.map((l, i) => `<tspan x="${x}" dy="${i === 0 ? 0 : lh + 'em'}">${esc(l)}</tspan>`).join('')
    this.el.push(`<text x="${x}" y="${y}" font-size="${size}" fill="${color}" text-anchor="${anchor}"${weight ? ` font-weight="${weight}"` : ''}>${tspans}</text>`)
  }

  box(x, y, w, h, title, lines = [], o = {}) {
    const color = o.color || INK
    this.rectS(x, y, w, h, { color, width: 2.2, fill: o.fill === false ? undefined : color, dash: o.dash })
    const cx = x + w / 2
    const titleArr = Array.isArray(title) ? title : [title]
    const totalTitle = titleArr.length
    const ty = y + (lines.length ? 28 : h / 2 - ((totalTitle - 1) * 10) + 5)
    this.text(cx, ty, titleArr, { size: o.titleSize || 16, color, anchor: 'middle', lh: 1.25, weight: 'bold' })
    if (lines.length) this.text(cx, ty + totalTitle * 22, lines, { size: o.lineSize || 12.5, color: SOFT, anchor: 'middle', lh: 1.35 })
  }

  dot(x, y, rr = 3, color = GRAY, opacity = 0.75) {
    this.el.push(`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rr}" fill="${color}" opacity="${opacity}"/>`)
  }

  blob(cx, cy, n, spreadX, spreadY, color, rr = 3.2, opacity = 0.7) {
    for (let i = 0; i < n; i++) {
      const a = this.r() * Math.PI * 2
      const d = Math.sqrt(this.r())
      this.dot(cx + Math.cos(a) * spreadX * d, cy + Math.sin(a) * spreadY * d, rr * (0.6 + this.r() * 0.8), color, opacity)
    }
  }

  crossout(x, y, w, h) {
    this.line(x + 8, y + 8, x + w - 8, y + h - 8, { color: RED, width: 3.5 })
    this.line(x + w - 8, y + 8, x + 8, y + h - 8, { color: RED, width: 3.5 })
  }

  save() {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${this.w} ${this.h}" width="${this.w}" height="${this.h}" font-family="${FONT}">\n${this.el.join('\n')}\n</svg>\n`
    writeFileSync(join(OUT, this.name), svg)
    console.log('wrote', this.name)
  }
}

// ---------------------------------------------------------------- 1. system overview
{
  const s = new Sketch('system-overview.svg', 1000, 620, 11, 'SplatAgent — how it’s wired')

  s.box(560, 80, 190, 62, 'CLEAN', ['full 40-tool editor'], { color: GREEN, titleSize: 15 })
  s.box(770, 80, 190, 62, 'UNDERSTAND', ['look-only analyst'], { color: BLUE, titleSize: 15 })
  s.text(760, 168, 'one stage switch gates the agent’s whole toolset', { size: 13, color: SOFT, anchor: 'middle' })

  s.box(50, 210, 300, 290, ['Browser', '(React + SparkJS)'], [
    'renders the gaussians',
    'editor tools + selection',
    'orbit / fly camera + pad',
    'chat panel + skill pills',
    '→ the agent’s EYES & HANDS',
  ], { color: BLUE, titleSize: 17, lineSize: 13.5 })

  s.box(430, 210, 290, 290, ['Python backend', '(FastAPI)'], [
    'splat data (numpy)',
    'metrics · editing · history',
    'agent loop:',
    'perceive → act → verify',
    'CPU-only — no CUDA',
  ], { color: GREEN, titleSize: 17, lineSize: 13.5 })

  s.box(790, 240, 170, 230, ['Model', 'provider'], [
    'Gemini (default)',
    'any OpenAI-compat',
    'local vLLM / Ollama',
    '',
    'must be a VLM —',
    'it sees frames',
  ], { color: VIOLET, titleSize: 16, lineSize: 12.5 })

  s.arrow(352, 290, 428, 290, { color: INK })
  s.text(390, 270, 'frames · state', { size: 12.5, color: SOFT, anchor: 'middle' })
  s.arrow(428, 420, 352, 420, { color: INK })
  s.text(390, 452, 'tool calls', { size: 12.5, color: SOFT, anchor: 'middle' })
  s.text(390, 358, 'REST + WS', { size: 12.5, color: SOFT, anchor: 'middle' })

  s.arrow(722, 320, 788, 320, { color: INK })
  s.arrow(788, 400, 722, 400, { color: INK })
  s.text(755, 300, 'sees', { size: 12.5, color: SOFT, anchor: 'middle' })
  s.text(755, 432, 'decides', { size: 12.5, color: SOFT, anchor: 'middle' })

  s.text(500, 560, 'no CUDA anywhere — the browser IS the renderer, and the rendered frame is what the model sees', { size: 14, color: RED, anchor: 'middle' })
  s.save()
}

// ---------------------------------------------------------------- 2. pipeline (the centerpiece)
{
  const s = new Sketch('pipeline.svg', 1080, 760, 22, 'From drone video to a splat you can inspect')

  const bw = 205, bh = 105, y1 = 165, y2 = 445
  s.box(40, y1, bw, bh, 'drone frames', ['Hurricane Ian sites', '4K video · no GPS', '(scale-free scenes)'], { color: INK })
  s.box(305, y1, bw, bh, '1 · thin frames', ['keep the sharpest per', 'window of 5', '3,525 → 705 frames'], { color: BLUE })
  s.box(570, y1, bw, bh, '2 · COLMAP SfM', ['GPU SIFT + vocab tree', '705/705 registered', '604K sparse points'], { color: BLUE })
  s.box(835, y1, bw, bh, '3 · pick a target', ['auto-detect buildings', 'top-down map → bbox', '+ per-building crops'], { color: GREEN })

  s.box(835, y2, bw, bh, '4 · train', ['gsplat MCMC · SH3', 'box-weighted budget', '+ box-masked loss'], { color: ORANGE })
  s.box(570, y2, bw, bh, '5 · prune', ['low opacity · oversized', 'out-of-box · needles', '(pancakes are kept!)'], { color: ORANGE })
  s.box(305, y2, bw, bh, '6 · package', ['.ply + manifest', 'holdout PSNR record', 'render checks'], { color: GREEN })
  s.box(40, y2, bw, bh, 'SplatAgent', ['inspect · clean', '· understand', '(this repo)'], { color: VIOLET })

  s.arrow(248, y1 + 52, 302, y1 + 52, { color: INK })
  s.arrow(513, y1 + 52, 567, y1 + 52, { color: INK })
  s.arrow(778, y1 + 52, 832, y1 + 52, { color: INK })
  s.arrow(937, y1 + bh + 4, 937, y2 - 4, { color: INK })
  s.arrow(832, y2 + 52, 778, y2 + 52, { color: INK })
  s.arrow(567, y2 + 52, 513, y2 + 52, { color: INK })
  s.arrow(302, y2 + 52, 248, y2 + 52, { color: INK })

  s.box(330, 300, 250, 84, 'VGGT-1B (feed-forward)', ['poses + points in one', 'pass — 3.5 s, no SfM'], { color: VIOLET, dash: '9 7' })
  s.text(455, 408, 'experimental shortcut — skips COLMAP entirely', { size: 12, color: VIOLET, anchor: 'middle' })
  s.arrow(400, y1 + bh + 3, 420, 297, { color: VIOLET, dash: '8 6' })
  s.arrow(583, 360, 832, 470, { color: VIOLET, dash: '8 6', bend: -30 })

  s.text(937, 610, ['⚠ the budget must scale', 'with covered area —', 'or PSNR collapses'], { size: 12.5, color: RED, anchor: 'middle' })
  s.text(672, 610, ['the loss mask is the OOM fix:', 'background pixels can never', 'demand coverage'], { size: 12.5, color: RED, anchor: 'middle' })
  s.text(407, 610, ['don’t trust orbit MP4s —', 'judge only from renders at', 'held-out real camera poses'], { size: 12.5, color: RED, anchor: 'middle' })
  s.text(142, 610, ['Iona bldg01:', '12,375 gaussians · 2.9 MB', 'holdout PSNR 21.7'], { size: 12.5, color: GREEN, anchor: 'middle' })
  s.save()
}

// ---------------------------------------------------------------- 3. editor: screen-space selection
{
  const s = new Sketch('editor-screenspace.svg', 1000, 540, 33, 'Screen-space selection — brush · lasso · polygon')

  s.rectS(50, 110, 580, 380, { color: GRAY, width: 2, fill: '#ffffff', fillOpacity: 0.5 })
  s.text(70, 476, 'viewport', { size: 12, color: SOFT })

  s.blob(240, 330, 55, 120, 80, GRAY)
  s.blob(430, 260, 30, 90, 70, GRAY)
  s.blob(520, 160, 6, 40, 20, GRAY, 2.5)

  s.ellipseS(200, 300, 42, 42, { color: BLUE, width: 2.5 })
  s.ellipseS(200, 300, 5, 5, { color: BLUE, width: 2 })
  s.text(200, 238, 'brush — [ and ] resize', { size: 13.5, color: BLUE, anchor: 'middle' })
  s.blob(200, 300, 12, 34, 34, BLUE, 3, 0.85)

  s.ellipseS(340, 400, 75, 45, { color: ORANGE, width: 2.5 })
  s.text(340, 406, 'lasso', { size: 13.5, color: ORANGE, anchor: 'middle' })

  const poly = [[420, 210], [520, 190], [560, 250], [510, 320], [430, 300]]
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length]
    s.line(a[0], a[1], b[0], b[1], { color: GREEN, width: 2.5 })
    s.dot(a[0], a[1], 4.5, GREEN, 1)
  }
  s.text(495, 165, 'polygon (≥3 pts, snap to close)', { size: 13.5, color: GREEN, anchor: 'middle' })

  s.text(670, 160, 'the grammar:', { size: 17, color: INK })
  s.text(670, 200, [
    '• paint or encircle splats',
    '   right on the screen',
    '• Alt = remove from selection',
    '• Esc = cancel mid-gesture',
    '• then: delete · keep ·',
    '   invert · clear',
  ], { size: 14.5, color: SOFT, lh: 1.6 })
  s.text(670, 420, ['same grammar as SuperSplat —', 'and the same tools the', 'agent calls, visibly'], { size: 13, color: VIOLET, lh: 1.5 })
  s.save()
}

// ---------------------------------------------------------------- 4. editor: volume selection
{
  const s = new Sketch('editor-volumes.svg', 1000, 540, 44, 'Volume selection — sphere & box, previewed before commit')

  s.rectS(50, 110, 580, 380, { color: GRAY, width: 2, fill: '#ffffff', fillOpacity: 0.5 })

  s.blob(240, 300, 40, 60, 55, BLUE, 3.2, 0.9)
  s.blob(240, 300, 25, 150, 110, GRAY, 3, 0.25)
  s.ellipseS(240, 300, 78, 78, { color: BLUE, width: 2.5 })
  s.ellipseS(240, 300, 78, 24, { color: BLUE, width: 1.8, dash: '7 6' })
  s.text(240, 195, 'sphere', { size: 14, color: BLUE, anchor: 'middle' })

  const bx = 400, by = 280, bs = 120, off = 34
  s.rectS(bx, by, bs, bs, { color: GREEN, width: 2.5 })
  s.rectS(bx + off, by - off, bs, bs, { color: GREEN, width: 1.6, dash: '6 6' })
  s.line(bx, by, bx + off, by - off, { color: GREEN, width: 1.6 })
  s.line(bx + bs, by, bx + bs + off, by - off, { color: GREEN, width: 1.6 })
  s.line(bx, by + bs, bx + off, by + bs - off, { color: GREEN, width: 1.6 })
  s.line(bx + bs, by + bs, bx + bs + off, by + bs - off, { color: GREEN, width: 1.6 })
  s.blob(bx + bs / 2 + 15, by + bs / 2 - 15, 30, 45, 40, GREEN, 3.2, 0.9)
  s.blob(560, 170, 8, 35, 25, GRAY, 3, 0.25)
  s.text(bx + bs / 2 + 18, by + bs + 40, 'box', { size: 14, color: GREEN, anchor: 'middle' })

  s.text(340, 470, 'outside the volume dims — SDF preview, live', { size: 13.5, color: SOFT, anchor: 'middle' })

  s.text(670, 170, 'how it plays:', { size: 17, color: INK })
  s.text(670, 210, [
    '• place · drag · scale the',
    '   volume in 3D',
    '• everything outside dims',
    '   before you commit',
    '• commit → delete or keep',
  ], { size: 14.5, color: SOFT, lh: 1.6 })
  s.text(670, 400, ['the agent uses the same', 'volumes — you see them', 'flash before any edit lands'], { size: 13, color: VIOLET, lh: 1.5 })
  s.save()
}

// ---------------------------------------------------------------- 5. editor: navigation
{
  const s = new Sketch('editor-navigation.svg', 1000, 540, 55, 'Navigation — orbit vs fly')

  s.rectS(50, 110, 420, 360, { color: GRAY, width: 2 })
  s.text(260, 148, 'ORBIT', { size: 17, color: BLUE, anchor: 'middle' })
  s.dot(260, 310, 6, INK, 1)
  s.text(260, 345, 'pivot', { size: 12, color: SOFT, anchor: 'middle' })
  s.ellipseS(260, 310, 140, 60, { color: BLUE, width: 2, dash: '8 7' })
  s.rectS(385, 285, 34, 24, { color: BLUE, width: 2 })
  s.line(385, 292, 372, 285, { color: BLUE, width: 2 })
  s.line(385, 302, 372, 309, { color: BLUE, width: 2 })
  s.arrow(310, 245, 190, 243, { color: BLUE, bend: -26 })
  s.text(260, 420, 'drag to circle the scene — great for a first look', { size: 13, color: SOFT, anchor: 'middle' })

  s.rectS(530, 110, 420, 360, { color: GRAY, width: 2 })
  s.text(740, 148, 'FLY', { size: 17, color: ORANGE, anchor: 'middle' })
  s.rectS(660, 250, 40, 28, { color: ORANGE, width: 2.2 })
  s.line(700, 258, 715, 250, { color: ORANGE, width: 2 })
  s.line(700, 270, 715, 278, { color: ORANGE, width: 2 })
  s.arrow(720, 250, 800, 200, { color: ORANGE })
  s.text(815, 190, 'drag = look', { size: 12.5, color: SOFT })
  const keys = [['W', 620, 330], ['A', 585, 365], ['S', 620, 365], ['D', 655, 365], ['Q', 710, 365], ['E', 745, 365]]
  for (const [k, kx, ky] of keys) {
    s.rectS(kx, ky, 28, 28, { color: INK, width: 1.8 })
    s.text(kx + 14, ky + 20, k, { size: 13, anchor: 'middle' })
  }
  s.text(680, 425, 'WASD move · Q/E up & down', { size: 12.5, color: SOFT, anchor: 'middle' })

  s.ellipseS(870, 330, 44, 44, { color: ORANGE, width: 2.2 })
  s.el.push(`<circle cx="870" cy="330" r="38" fill="${ORANGE}" opacity="0.15"/>`)
  s.arrow(870, 316, 870, 300, { color: ORANGE })
  s.arrow(870, 344, 870, 360, { color: ORANGE })
  s.arrow(856, 330, 840, 330, { color: ORANGE })
  s.arrow(884, 330, 900, 330, { color: ORANGE })
  s.text(870, 398, ['on-screen pad — lights up for', 'ANY driver: you or the agent'], { size: 12, color: ORANGE, anchor: 'middle', lh: 1.4 })
  s.save()
}

// ---------------------------------------------------------------- 6. editor: one history
{
  const s = new Sketch('editor-history.svg', 1000, 560, 66, 'One edit history — human and agent share it')

  s.box(70, 160, 210, 84, 'you', ['brush · lasso · volumes', 'delete / keep'], { color: BLUE })
  s.box(70, 330, 210, 84, 'the agent', ['same tools, called', 'through the loop'], { color: VIOLET })
  s.box(390, 240, 240, 94, '/edit', ['delete_by_ids', 'keep_only_ids'], { color: ORANGE })
  s.box(720, 240, 230, 94, 'backend History', ['the authoritative', 'undo stack'], { color: GREEN })

  s.arrow(283, 202, 388, 270, { color: BLUE })
  s.arrow(283, 372, 388, 305, { color: VIOLET })
  s.arrow(633, 287, 717, 287, { color: ORANGE })

  s.rectS(390, 400, 240, 66, { color: GRAY, width: 2, dash: '8 7' })
  s.text(510, 428, 'local undo mirror', { size: 14, color: SOFT, anchor: 'middle' })
  s.text(510, 450, 'instant Ctrl+Z in the viewer', { size: 12, color: SOFT, anchor: 'middle' })
  s.line(510, 337, 510, 397, { color: GRAY, width: 1.8, dash: '6 6' })

  s.text(835, 400, ['stable splat IDs survive', 'compaction — the viewer', 'adopts GET /ids on reload'], { size: 12.5, color: SOFT, anchor: 'middle', lh: 1.4 })
  s.text(500, 515, 'a failed backend edit reloads the authoritative scene (with a toast) — the two never drift', { size: 13.5, color: RED, anchor: 'middle' })
  s.save()
}

// ---------------------------------------------------------------- 7. agent: analyst
{
  const s = new Sketch('agent-analyst.svg', 1000, 560, 77, 'Agent 1 — the Analyst (Understand stage)')

  s.box(55, 170, 210, 100, 'you ask', ['“how many damaged', 'buildings are there?”'], { color: BLUE })
  s.box(330, 170, 250, 100, 'the app flies a survey', ['framed orbit around the', 'scene — the model does', 'NOT drive the camera'], { color: GREEN })
  s.box(645, 170, 220, 100, 'frames captured', ['persisted per scene', 'conversation — follow-ups', 'reuse the same views'], { color: ORANGE })
  s.box(240, 390, 330, 100, 'model answers', ['grounded ONLY in what the', 'survey frames actually show'], { color: VIOLET })

  s.arrow(267, 220, 327, 220, { color: INK })
  s.arrow(582, 220, 642, 220, { color: INK })
  s.arrow(740, 273, 480, 388, { color: INK, bend: 24 })

  s.rectS(680, 390, 190, 90, { color: GRAY, width: 2 })
  s.text(775, 428, 'edit tools', { size: 15, color: SOFT, anchor: 'middle' })
  s.crossout(680, 390, 190, 90)
  s.text(775, 510, ['rejected at spec AND dispatch —', 'the analyst cannot touch the scene'], { size: 12, color: RED, anchor: 'middle', lh: 1.4 })
  s.save()
}

// ---------------------------------------------------------------- 8. agent: cleaner
{
  const s = new Sketch('agent-cleanup.svg', 1000, 640, 88, 'Agent 2 — the Cleaner (Clean stage): propose → approve → edit')

  s.box(60, 180, 230, 100, '1 · look around', ['fly · capture · size up', 'floaters & junk'], { color: BLUE })
  s.box(380, 180, 250, 110, '2 · propose a decision', ['crop-outside-box', 'delete / keep-only selection', 'bulk-edit sweeps'], { color: ORANGE })
  s.box(720, 180, 230, 110, '3 · ProposalCard', ['SDF dim + wireframe', 'preview — you review'], { color: VIOLET })
  s.box(380, 450, 250, 100, '4 · gated edit', ['exactly the approved op —', 'nothing more, nothing else'], { color: GREEN })

  s.arrow(292, 230, 377, 230, { color: INK })
  s.arrow(632, 232, 717, 232, { color: INK })
  s.arrow(800, 293, 580, 448, { color: INK, bend: 26 })
  s.text(740, 390, 'approve', { size: 13.5, color: GREEN })
  s.arrow(378, 500, 175, 285, { color: INK, bend: 26 })
  s.text(200, 420, ['verify,', 'next round'], { size: 12.5, color: SOFT, anchor: 'middle', lh: 1.35 })

  s.arrow(718, 195, 635, 195, { color: VIOLET, dash: '7 6', bend: -22 })
  s.text(676, 148, ['adjust — your feedback', 're-enters the loop'], { size: 12, color: VIOLET, anchor: 'middle', lh: 1.35 })
  s.text(836, 330, 'reject → dropped, agent moves on', { size: 11.5, color: SOFT, anchor: 'middle' })

  s.text(500, 595, 'no destructive edit EVER fires without a banked approval — the approval binds the exact reviewed operation', { size: 13.5, color: RED, anchor: 'middle' })
  s.text(150, 560, ['selection tint marks', 'the pending set'], { size: 12, color: SOFT, anchor: 'middle', lh: 1.4 })
  s.text(845, 560, ['camera moves don’t pause', 'review · Stop ends cleanly'], { size: 12, color: SOFT, anchor: 'middle', lh: 1.4 })
  s.save()
}

console.log('done')
