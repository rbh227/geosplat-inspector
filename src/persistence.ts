/**
 * Session persistence for the loaded scene (Bug 1).
 *
 * A page refresh used to wipe the splat entirely: the renderer state and the
 * loaded File live only in browser memory. We persist the backend scene id — the
 * authoritative, edit-reflecting handle — plus the file name, the original
 * (baseline) splat count for the export badge, and the last camera pose, then
 * restore them on mount.
 *
 * Only backend `.ply` scenes are recoverable: a view-only `.splat`/`.spz` drop
 * leaves no File and no backend id to reload, so those are never persisted (and
 * loading one clears any stale record).
 *
 * `sessionStorage` (not `localStorage`) is deliberate: the record survives a
 * refresh but clears when the tab closes, matching the backend's own in-memory
 * scene lifetime closely enough that stale-record fallback is the exception.
 */

const KEY = 'splatagent.scene.v1'

export interface PersistedCamera {
  position: [number, number, number]
  target: [number, number, number]
}

export interface PersistedScene {
  sceneId: string
  fileName: string | null
  /** Original splat count at first load — keeps the "N removed" badge correct. */
  baseline: number
  camera: PersistedCamera | null
}

export function savePersistedScene(scene: PersistedScene): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(scene))
  } catch {
    /* storage disabled or full — persistence is best-effort, never fatal */
  }
}

export function loadPersistedScene(): PersistedScene | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as PersistedScene
    if (!parsed || typeof parsed.sceneId !== 'string') return null
    return parsed
  } catch {
    return null
  }
}

export function clearPersistedScene(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* non-fatal */
  }
}

/** Merge a fresh camera pose into the existing record (called on unload). */
export function updatePersistedCamera(camera: PersistedCamera): void {
  const cur = loadPersistedScene()
  if (!cur) return
  savePersistedScene({ ...cur, camera })
}
