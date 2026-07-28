export type AnalystStatus = 'no-scene' | 'scene-gone' | 'ready'

/**
 * Which state the analyst window renders. Pure, and in its own module so the
 * page file exports only its component (react-refresh/only-export-components).
 */
export function analystStatus(sceneId: string | null, gone: boolean): AnalystStatus {
  if (!sceneId) return 'no-scene'
  return gone ? 'scene-gone' : 'ready'
}
