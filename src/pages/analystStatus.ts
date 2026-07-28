export type AnalystStatus = 'no-scene' | 'loading' | 'scene-gone' | 'ready'

/**
 * Which state the analyst window renders.
 *
 * `hasScene` (is something actually loaded?) is checked FIRST and deliberately:
 * deriving from the URL id alone meant dropping a replacement .ply in the
 * no-scene or scene-gone state loaded it behind an overlay that never cleared,
 * while any non-empty URL read as "ready" before its (possibly very long) load
 * had finished.
 *
 * Pure, so it can be tested without a DOM.
 */
export function analystStatus(
  sceneId: string | null,
  gone: boolean,
  hasScene: boolean,
): AnalystStatus {
  if (hasScene) return 'ready'          // something is on screen, whatever its origin
  if (gone) return 'scene-gone'         // the URL's scene is gone and nothing replaced it
  if (sceneId) return 'loading'         // an id to fetch, not resolved yet
  return 'no-scene'
}
