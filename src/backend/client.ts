/**
 * Thin REST client for the GeoSplat Inspector backend (Agent 4's API).
 *
 * The browser is the renderer AND the agent's eyes; this module is the seam
 * that turns a loaded scene into a backend `scene_id` and kicks off agent
 * runs. Trace/commands stream back over the WebSocket (see `@agent`), not here.
 *
 * URLs are SAME-ORIGIN relative by default. In dev, Vite proxies `/scene`,
 * `/agent`, `/ws`, etc. to the backend (vite.config.ts) — this avoids CORS and,
 * critically, the COEP `require-corp` cross-origin block + WebGL canvas taint
 * that would otherwise break the agent's `capture_frame`. In production the
 * backend serves the built frontend, so same-origin is already correct.
 * Set `VITE_BACKEND_URL` only to talk to a remote backend directly.
 */

const BACKEND_URL: string =
  (import.meta.env.VITE_BACKEND_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export interface UploadResult {
  id: string
  metrics: Record<string, unknown>
}

/** Absolute-or-relative URL of the backend-served (current alive set) .ply. */
export function scenePlyUrl(sceneId: string): string {
  return `${BACKEND_URL}/scene/${sceneId}.ply`
}

/** WebSocket URL for a scene's renderer channel. */
export function sceneWsUrl(sceneId: string): string {
  if (BACKEND_URL) {
    return `${BACKEND_URL.replace(/^http/, 'ws')}/ws/${sceneId}`
  }
  // Same-origin: derive ws(s):// from the current page origin (Vite proxies it).
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/${sceneId}`
}

/** Is a filename one the backend can load? (INRIA binary .ply only.) */
export function isBackendLoadable(name: string): boolean {
  return name.toLowerCase().endsWith('.ply')
}

/** POST /scene — upload a .ply, returns its id + initial metrics. */
export async function uploadScene(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file, file.name)
  const res = await fetch(`${BACKEND_URL}/scene`, { method: 'POST', body: form })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`upload failed (${res.status}): ${detail}`)
  }
  return (await res.json()) as UploadResult
}

/** GET /metrics — recompute metrics for the current alive set of a scene. */
export async function getMetrics(sceneId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${BACKEND_URL}/metrics?scene_id=${encodeURIComponent(sceneId)}`)
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`metrics fetch failed (${res.status}): ${detail}`)
  }
  return (await res.json()) as Record<string, unknown>
}

export interface EditCounts {
  before: number
  after: number
}

/**
 * POST /edit with an ID-based op (v0.2). `ids` are ORIGINAL splat ids from the
 * viewer's stable ID map; the backend masks by id and snapshots one shared
 * history. The caller applies the same edit locally first (optimistic) and
 * reloads the authoritative scene if this call fails (KTD2).
 */
export async function editByIds(
  sceneId: string,
  op: 'delete_by_ids' | 'keep_only_ids',
  ids: ArrayLike<number>,
): Promise<EditCounts> {
  const res = await fetch(`${BACKEND_URL}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, op, params: { ids: Array.from(ids) } }),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`edit failed (${res.status}): ${detail}`)
  }
  return (await res.json()) as EditCounts
}

/**
 * GET /ids — the backend's alive original Gaussian ids in export order.
 * Adopted by the viewer after any backend-driven reload so both sides keep
 * speaking the same stable-ID space.
 */
export async function getAliveIds(sceneId: string): Promise<Uint32Array> {
  const res = await fetch(`${BACKEND_URL}/ids?scene_id=${encodeURIComponent(sceneId)}`)
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`ids fetch failed (${res.status}): ${detail}`)
  }
  const body = (await res.json()) as { ids: number[] }
  return Uint32Array.from(body.ids)
}

/** POST /undo | /redo — backend History is the one undo authority (KTD2). */
export async function historyOp(sceneId: string, op: 'undo' | 'redo'): Promise<{ ok: boolean; count: number }> {
  const res = await fetch(`${BACKEND_URL}/${op}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId }),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`${op} failed (${res.status}): ${detail}`)
  }
  return (await res.json()) as { ok: boolean; count: number }
}

/** POST /agent/run — kick off the agent loop; results stream over the WS.
 *  `stage` gates the agent's tool surface (Clean = editor, Understand = look-only). */
export async function runAgent(
  sceneId: string,
  prompt: string,
  stage: 'clean' | 'understand' = 'clean',
): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_id: sceneId, prompt, stage }),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`agent run failed (${res.status}): ${detail}`)
  }
}

export interface SkillInfo {
  name: string
  stage: string
  description: string
  recipe: string
}

/** GET /agent/skills — the shared skills vocabulary for a stage (R10/R11). */
export async function getSkills(stage: 'clean' | 'understand'): Promise<SkillInfo[]> {
  const res = await fetch(`${BACKEND_URL}/agent/skills?stage=${stage}`)
  if (!res.ok) return []
  const body = (await res.json()) as { skills: SkillInfo[] }
  return body.skills ?? []
}

export { BACKEND_URL }
