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
  count: number
}

/** Which copy of a scene to fetch: the live edited set, or the untouched upload. */
export type SceneVersion = 'current' | 'original'

/** Absolute-or-relative URL of the backend-served .ply. `original` returns the
 *  upload as-is — a viewing lens for before/after, it changes no server state. */
export function scenePlyUrl(sceneId: string, version: SceneVersion = 'current'): string {
  const query = version === 'original' ? '?version=original' : ''
  return `${BACKEND_URL}/scene/${sceneId}.ply${query}`
}

export interface AgentHistoryMessage {
  role: string
  content: string
}

/** GET /agent/history — the conversation the BACKEND keeps for this scene.
 *  It outlives a browser reload, so the bubbles can be put back. */
export async function getAgentHistory(sceneId: string): Promise<AgentHistoryMessage[]> {
  const res = await fetch(`${BACKEND_URL}/agent/history?scene_id=${encodeURIComponent(sceneId)}`)
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`agent history fetch failed (${res.status}): ${detail}`)
  }
  const body = (await res.json()) as { messages?: AgentHistoryMessage[] }
  return body.messages ?? []
}

/** WebSocket URL for a scene's renderer channel.
 *
 *  `clientId` identifies the WINDOW. The editor and the analyst are two
 *  renderers on one scene; without distinct ids the backend keyed sockets by
 *  scene alone and each window's connect closed the other's. */
export function sceneWsUrl(sceneId: string, clientId?: string): string {
  const query = clientId ? `?client=${encodeURIComponent(clientId)}` : ''
  if (BACKEND_URL) {
    return `${BACKEND_URL.replace(/^http/, 'ws')}/ws/${sceneId}${query}`
  }
  // Same-origin: derive ws(s):// from the current page origin (Vite proxies it).
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/${sceneId}${query}`
}

/** Is a filename one the backend can load? (INRIA binary .ply only.) */
export function isBackendLoadable(name: string): boolean {
  return name.toLowerCase().endsWith('.ply')
}

/** POST /scene — upload a .ply, returns its id + alive count. Metrics are NOT
 *  computed here (they cost minutes on a large scene); use getMetrics(). */
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
  clientId?: string,
): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // client_id binds the run to THIS window's renderer, so with the editor and
    // analyst both open the tools execute where the operator started them.
    body: JSON.stringify({ scene_id: sceneId, prompt, stage, client_id: clientId ?? null }),
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

// ---- Model picker (in-app model settings) ---------------------------------

export interface ProviderInfo {
  id: string
  label: string
  provider: string
  default_model: string
  needs_key: boolean
  supports_base_url: boolean
  key_env_vars?: string[]
  key_help_url?: string
  default_base_url?: string
  blurb: string
  key_in_env: boolean
}

export interface ModelConfig {
  preset: string
  provider: string
  model: string | null
  base_url: string | null
  key_set: boolean
  key_source: 'ui' | 'env' | null
  source: 'ui' | 'env' | 'default'
}

export interface ModelConfigInput {
  preset: string
  model?: string | null
  /** Omit to keep the currently-saved key; pass "" to clear it. */
  api_key?: string | null
  base_url?: string | null
}

export interface TestConnectionResult {
  ok: boolean
  model?: string | null
  error?: string | null
}

/** GET /config/providers — the model picker's registry (never carries key values). */
export async function getProviders(): Promise<ProviderInfo[]> {
  const res = await fetch(`${BACKEND_URL}/config/providers`)
  if (!res.ok) return []
  const body = (await res.json()) as { providers: ProviderInfo[] }
  return body.providers ?? []
}

/** GET /config/model — the current selection. Degrades to null so the UI can
 *  still render (e.g. offline backend) without blocking on model config. */
export async function getModelConfig(): Promise<ModelConfig | null> {
  const res = await fetch(`${BACKEND_URL}/config/model`)
  if (!res.ok) return null
  return (await res.json()) as ModelConfig
}

/** POST /config/model — save a selection. The response never contains a key. */
export async function saveModelConfig(req: ModelConfigInput): Promise<ModelConfig> {
  const res = await fetch(`${BACKEND_URL}/config/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`save model config failed (${res.status}): ${detail}`)
  }
  return (await res.json()) as ModelConfig
}

/** POST /config/test — cheap live round-trip so the "Test connection" button
 *  can confirm a key/endpoint works before Save. */
export async function testModelConfig(req?: Partial<ModelConfigInput>): Promise<TestConnectionResult> {
  const res = await fetch(`${BACKEND_URL}/config/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req ?? {}),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    return { ok: false, error: `test request failed (${res.status}): ${detail}` }
  }
  return (await res.json()) as TestConnectionResult
}

export { BACKEND_URL }
