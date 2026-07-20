import { useCallback, useEffect, useRef } from 'react'
import * as THREE from 'three'
import type { ViewerHandle } from '../types/viewer.ts'
import { composeMatrices, projectToScreen, selectInBox, selectInMask, selectInPolygon, selectInSphere } from './selection.ts'

/**
 * Pointer-interaction layer for the selection tools (R4/R5, KTD4/KTD5).
 *
 * Tool UX follows SuperSplat (MIT © PlayCanvas Ltd): brush paints a mask,
 * lasso freehand-closes, polygon click-places (≥3 vertices; double-click or
 * first-point snap closes), sphere/box drag a live SDF-dimmed volume.
 * Escape cancels any in-progress interaction. `[` / `]` resize the brush.
 *
 * While a tool is active this overlay sits above the renderer canvas and
 * shields it from pointer events — camera controls are inert by construction.
 */

export type SelectionTool = 'brush' | 'lasso' | 'polygon' | 'sphere' | 'box'

const FIRST_POINT_SNAP_PX = 10
const MIN_POLYGON_VERTICES = 3
const STROKE_STYLE = 'rgba(130, 190, 255, 0.85)'
const FILL_STYLE = 'rgba(130, 190, 255, 0.25)'
// Erase mode paints destructive red so an erase gesture never reads as a select (R1).
const ERASE_STROKE_STYLE = 'rgba(255, 110, 100, 0.85)'
const ERASE_FILL_STYLE = 'rgba(255, 110, 100, 0.25)'

interface SelectionOverlayProps {
  viewerRef: React.RefObject<ViewerHandle | null>
  tool: SelectionTool | null
  /** Hold Alt while committing to remove from the selection instead of adding. */
  onSelectionChange?: (count: number) => void
  /** Any pointer-down here is manual input (agent pause trigger, R14). */
  onManualInput?: () => void
  /** Escape with no gesture in progress exits to pointer mode (R6/KTD5). */
  onExitTool?: () => void
  /** Erase mode (R1/KTD2): gestures always add, and each commit fires onGestureCommit. */
  eraseMode?: boolean
  /** Fired after a gesture commits while eraseMode is on — the app deletes the selection. */
  onGestureCommit?: () => void
}

export default function SelectionOverlay({
  viewerRef, tool, onSelectionChange, onManualInput, onExitTool,
  eraseMode = false, onGestureCommit,
}: SelectionOverlayProps) {
  const strokeStyle = eraseMode ? ERASE_STROKE_STYLE : STROKE_STYLE
  const fillStyle = eraseMode ? ERASE_FILL_STYLE : FILL_STYLE
  const displayRef = useRef<HTMLCanvasElement>(null)
  const maskRef = useRef<HTMLCanvasElement | null>(null) // offscreen, brush only
  const brushRadius = useRef(24)

  // in-progress interaction state (refs — no re-render per pointermove)
  const drawing = useRef(false)
  const lassoPath = useRef<number[]>([])
  const polygonVerts = useRef<number[]>([])
  const volumeAnchor = useRef<THREE.Vector3 | null>(null) // world space
  const volumeSize = useRef(0)
  const cursor = useRef<{ x: number; y: number } | null>(null)

  /* ---- canvas sizing --------------------------------------------------- */

  const syncSize = useCallback(() => {
    const display = displayRef.current
    if (!display) return
    const { clientWidth, clientHeight } = display
    if (display.width !== clientWidth || display.height !== clientHeight) {
      display.width = clientWidth
      display.height = clientHeight
    }
    if (!maskRef.current) maskRef.current = document.createElement('canvas')
    const mask = maskRef.current
    if (mask.width !== clientWidth || mask.height !== clientHeight) {
      mask.width = clientWidth
      mask.height = clientHeight
    }
  }, [])

  useEffect(() => {
    syncSize()
    window.addEventListener('resize', syncSize)
    return () => window.removeEventListener('resize', syncSize)
  }, [syncSize])

  /* ---- shared helpers --------------------------------------------------- */

  const clearCanvases = useCallback(() => {
    const display = displayRef.current
    display?.getContext('2d')?.clearRect(0, 0, display.width, display.height)
    const mask = maskRef.current
    mask?.getContext('2d')?.clearRect(0, 0, mask.width, mask.height)
  }, [])

  const resetInteraction = useCallback(() => {
    drawing.current = false
    lassoPath.current = []
    polygonVerts.current = []
    volumeAnchor.current = null
    volumeSize.current = 0
    clearCanvases()
    viewerRef.current?.clearSelectionPreview()
  }, [clearCanvases, viewerRef])

  /** Project all live centers to the overlay's pixel space. */
  const projectAll = useCallback(() => {
    const display = displayRef.current
    const viewer = viewerRef.current
    if (!viewer || !display) return null
    const cw = viewer.getCentersWorld()
    if (!cw) return null
    const cam = viewer.getCamera()
    cam.updateMatrixWorld()
    const viewProj = composeMatrices(
      Array.from(cam.projectionMatrix.elements),
      Array.from(cam.matrixWorldInverse.elements),
    )
    return { ...projectToScreen(cw.centers, viewProj, display.width, display.height), cw }
  }, [viewerRef])

  // Every tool's gesture (brush stroke, lasso close, both polygon close paths,
  // sphere/box commit) funnels through here exactly once, so this is the one
  // seam erase mode needs (KTD2). Alt-remove is forced off while erasing —
  // the selection is transient, so there is nothing to remove from (KTD3).
  const commitIndices = useCallback((indices: Uint32Array, ids: Uint32Array, remove: boolean) => {
    const viewer = viewerRef.current
    if (!viewer) return
    const selected = new Array<number>(indices.length)
    for (let i = 0; i < indices.length; i++) selected[i] = ids[indices[i]]
    const count = viewer.updateSelection(selected, remove && !eraseMode ? 'remove' : 'add')
    onSelectionChange?.(count)
    if (eraseMode) onGestureCommit?.()
  }, [viewerRef, onSelectionChange, eraseMode, onGestureCommit])

  /** World-space point on the plane through the look-target, from pixel coords. */
  const pointOnTargetPlane = useCallback((px: number, py: number): THREE.Vector3 | null => {
    const display = displayRef.current
    const viewer = viewerRef.current
    if (!viewer || !display) return null
    const cam = viewer.getCamera()
    const ndc = new THREE.Vector2((px / display.width) * 2 - 1, -(py / display.height) * 2 + 1)
    const ray = new THREE.Raycaster()
    ray.setFromCamera(ndc, cam)
    const { target } = viewer.getCameraPose()
    const normal = cam.getWorldDirection(new THREE.Vector3())
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, target)
    const out = new THREE.Vector3()
    return ray.ray.intersectPlane(plane, out) ? out : null
  }, [viewerRef])

  /* ---- per-frame display drawing ---------------------------------------- */

  const redrawDisplay = useCallback(() => {
    const display = displayRef.current
    const ctx = display?.getContext('2d')
    if (!display || !ctx) return
    ctx.clearRect(0, 0, display.width, display.height)

    // brush: mirror the offscreen mask for feedback + ring cursor (DL7)
    if (tool === 'brush') {
      if (maskRef.current) ctx.drawImage(maskRef.current, 0, 0)
      if (cursor.current) {
        ctx.strokeStyle = eraseMode ? ERASE_STROKE_STYLE : 'rgba(255,255,255,0.5)'
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.arc(cursor.current.x, cursor.current.y, brushRadius.current, 0, Math.PI * 2)
        ctx.stroke()
      }
      return
    }

    // lasso / polygon: in-progress outline
    const path = tool === 'lasso' ? lassoPath.current : polygonVerts.current
    if ((tool === 'lasso' || tool === 'polygon') && path.length >= 2) {
      ctx.strokeStyle = strokeStyle
      ctx.fillStyle = fillStyle
      ctx.lineWidth = 1.5
      ctx.beginPath()
      ctx.moveTo(path[0], path[1])
      for (let i = 2; i < path.length; i += 2) ctx.lineTo(path[i], path[i + 1])
      if (tool === 'polygon' && cursor.current) ctx.lineTo(cursor.current.x, cursor.current.y)
      ctx.stroke()
      if (tool === 'polygon' && path.length >= 2) {
        // first-vertex snap affordance
        ctx.beginPath()
        ctx.arc(path[0], path[1], FIRST_POINT_SNAP_PX / 2, 0, Math.PI * 2)
        ctx.stroke()
      }
    }
  }, [tool, eraseMode, strokeStyle, fillStyle])

  /* ---- resolve helpers (declared before the pointer handlers use them) --- */

  const paintBrushDot = useCallback((x: number, y: number) => {
    const ctx = maskRef.current?.getContext('2d')
    if (!ctx) return
    ctx.fillStyle = fillStyle
    ctx.beginPath()
    ctx.arc(x, y, brushRadius.current, 0, Math.PI * 2)
    ctx.fill()
  }, [fillStyle])

  const resolveBrush = useCallback((remove: boolean) => {
    const proj = projectAll()
    const mask = maskRef.current
    const ctx = mask?.getContext('2d')
    if (!proj || !mask || !ctx) return
    const data = ctx.getImageData(0, 0, mask.width, mask.height).data
    const hits = selectInMask(proj.xy, proj.visible, data, mask.width, mask.height)
    commitIndices(hits, proj.cw.ids, remove)
  }, [projectAll, commitIndices])

  const resolvePolygonPath = useCallback((path: number[], remove: boolean) => {
    if (path.length < MIN_POLYGON_VERTICES * 2) return
    const proj = projectAll()
    if (!proj) return
    const hits = selectInPolygon(proj.xy, proj.visible, path)
    commitIndices(hits, proj.cw.ids, remove)
  }, [projectAll, commitIndices])

  const commitPolygon = useCallback((remove: boolean) => {
    resolvePolygonPath(polygonVerts.current, remove)
    polygonVerts.current = []
    clearCanvases()
  }, [resolvePolygonPath, clearCanvases])

  /* ---- pointer handlers -------------------------------------------------- */

  const toLocal = (e: { clientX: number; clientY: number; currentTarget: EventTarget }): { x: number; y: number } => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    return { x: e.clientX - rect.left, y: e.clientY - rect.top }
  }

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if (!tool || !viewerRef.current) return
    onManualInput?.()
    syncSize()
    const p = toLocal(e)
    cursor.current = p
    ;(e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId)

    if (tool === 'brush') {
      drawing.current = true
      paintBrushDot(p.x, p.y)
    } else if (tool === 'lasso') {
      drawing.current = true
      lassoPath.current = [p.x, p.y]
    } else if (tool === 'polygon') {
      const verts = polygonVerts.current
      const nearFirst =
        verts.length >= MIN_POLYGON_VERTICES * 2 &&
        Math.hypot(p.x - verts[0], p.y - verts[1]) <= FIRST_POINT_SNAP_PX
      if (nearFirst) {
        commitPolygon(e.altKey)
        return
      }
      verts.push(p.x, p.y)
    } else {
      // sphere / box: anchor the volume on the target plane
      const world = pointOnTargetPlane(p.x, p.y)
      if (world) {
        drawing.current = true
        volumeAnchor.current = world
        volumeSize.current = 0
      }
    }
    redrawDisplay()
  }, [tool, viewerRef, onManualInput, syncSize, paintBrushDot, commitPolygon, pointOnTargetPlane, redrawDisplay])

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!tool) return
    const viewer = viewerRef.current
    const p = toLocal(e)
    cursor.current = p

    if (tool === 'brush' && drawing.current) {
      paintBrushDot(p.x, p.y)
    } else if (tool === 'lasso' && drawing.current) {
      lassoPath.current.push(p.x, p.y)
    } else if ((tool === 'sphere' || tool === 'box') && drawing.current && volumeAnchor.current && viewer) {
      const world = pointOnTargetPlane(p.x, p.y)
      if (world) {
        volumeSize.current = world.distanceTo(volumeAnchor.current)
        const a = volumeAnchor.current
        // world → mesh-local (backend) coords: the mesh transform is exactly
        // the Y-flip (rotation.x = π, no translation), which is self-inverse.
        const local = [a.x, -a.y, -a.z]
        viewer.showSelectionPreview(
          tool,
          local,
          tool === 'sphere' ? [volumeSize.current] : [volumeSize.current, volumeSize.current, volumeSize.current],
        )
      }
    }
    redrawDisplay()
  }, [tool, viewerRef, paintBrushDot, pointOnTargetPlane, redrawDisplay])

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    const viewer = viewerRef.current
    if (!tool || !viewer) return
    const remove = e.altKey

    if (tool === 'brush' && drawing.current) {
      drawing.current = false
      resolveBrush(remove)
      clearCanvases()
      redrawDisplay()
    } else if (tool === 'lasso' && drawing.current) {
      drawing.current = false
      resolvePolygonPath(lassoPath.current, remove)
      lassoPath.current = []
      clearCanvases()
    } else if ((tool === 'sphere' || tool === 'box') && drawing.current && volumeAnchor.current) {
      drawing.current = false
      const cw = viewer.getCentersWorld()
      if (cw && volumeSize.current > 1e-6) {
        const a = volumeAnchor.current
        const r = volumeSize.current
        const hits = tool === 'sphere'
          ? selectInSphere(cw.centers, [a.x, a.y, a.z], r)
          : selectInBox(cw.centers, [a.x - r, a.y - r, a.z - r], [a.x + r, a.y + r, a.z + r])
        commitIndices(hits, cw.ids, remove)
      }
      volumeAnchor.current = null
      volumeSize.current = 0
      viewer.clearSelectionPreview()
    }
  }, [tool, viewerRef, resolveBrush, resolvePolygonPath, commitIndices, clearCanvases, redrawDisplay])

  const onDoubleClick = useCallback((e: React.MouseEvent) => {
    if (tool === 'polygon' && polygonVerts.current.length >= MIN_POLYGON_VERTICES * 2) {
      commitPolygon(e.altKey)
    }
  }, [tool, commitPolygon])

  /* ---- keyboard: Escape cancels, [ ] resize brush ------------------------ */

  useEffect(() => {
    if (!tool) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Two-step exit (KTD5): first Escape cancels an in-progress gesture,
        // Escape with nothing in progress drops to pointer mode.
        const inProgress =
          drawing.current ||
          lassoPath.current.length > 0 ||
          polygonVerts.current.length > 0 ||
          volumeAnchor.current !== null
        if (inProgress) {
          resetInteraction()
          redrawDisplay()
        } else {
          onExitTool?.()
        }
      } else if (tool === 'brush' && (e.key === '[' || e.key === ']')) {
        brushRadius.current = Math.max(4, Math.min(200, brushRadius.current + (e.key === ']' ? 4 : -4)))
        redrawDisplay()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tool, resetInteraction, redrawDisplay, onExitTool])

  /* tool switched off / changed: drop any in-progress state */
  useEffect(() => {
    resetInteraction()
  }, [tool, resetInteraction])

  if (!tool) return null

  return (
    <canvas
      ref={displayRef}
      className="absolute inset-0 z-10 h-full w-full cursor-crosshair"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={onDoubleClick}
    />
  )
}
