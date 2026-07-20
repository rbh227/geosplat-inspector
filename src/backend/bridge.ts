/**
 * Adapts the existing renderer's `ViewerHandle` to the narrow `RendererBridge`
 * slice the agent layer (`@agent`) drives. `ViewerHandle` already structurally
 * satisfies `RendererBridge`; the only real work here is rewriting a
 * backend-relative reload URL (`/scene/{id}.ply`) to the backend origin, since
 * the renderer is served from the Vite origin, not the API.
 */
import type { RendererBridge } from '@agent'
import type { ViewerHandle } from '../types/viewer'
import { BACKEND_URL } from './client'

export function makeRendererBridge(viewer: ViewerHandle): RendererBridge {
  return {
    setCameraPose: (p, t, animate) => viewer.setCameraPose(p, t, animate),
    getCameraPose: () => viewer.getCameraPose(),
    getBoundingBox: () => viewer.getBoundingBox(),
    getSceneCore: () => viewer.getSceneCore(),
    getSceneRevision: () => viewer.getSceneRevision(),
    getCamera: () => viewer.getCamera(),
    getRenderer: () => viewer.getRenderer(),
    getOverlayGroup: () => viewer.getOverlayGroup(),
    renderOnce: () => viewer.renderOnce(),
    isLoaded: () => viewer.isLoaded(),
    loadSplat: (url: string) => {
      const abs = url.startsWith('/scene/') ? `${BACKEND_URL}${url}` : url
      return viewer.loadSplat(abs)
    },
    // v0.2 — shared selection/movement action layer
    getCentersWorld: () => viewer.getCentersWorld(),
    getSelectionIds: () => viewer.getSelectionIds(),
    updateSelection: (ids, mode) => viewer.updateSelection(ids, mode),
    clearSelection: () => viewer.clearSelection(),
    invertSelection: () => viewer.invertSelection(),
    getSelectionSummary: () => viewer.getSelectionSummary(),
    showSelectionPreview: (s, c, z) => viewer.showSelectionPreview(s, c, z),
    clearSelectionPreview: () => viewer.clearSelectionPreview(),
    setMovementInput: (d, a) => viewer.setMovementInput(d, a),
    setRotationInput: (d, a) => viewer.setRotationInput(d, a),
  }
}
