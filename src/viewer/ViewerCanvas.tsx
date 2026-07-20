import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  useCallback,
} from 'react'
import type { MoveDirection, RotateDirection, ViewerHandle, ViewerState } from '../types/viewer.ts'
import { SceneManager } from './SceneManager.ts'
import { KEY_TO_DIRECTION } from './flyController.ts'

/* ------------------------------------------------------------------ */
/*  Props                                                             */
/* ------------------------------------------------------------------ */

interface ViewerCanvasProps {
  onStateChange?: (state: ViewerState) => void
  /** Active movement directions changed (any source: keys, pad, agent). */
  onMovementChange?: (dirs: MoveDirection[]) => void
  /** Active rotate directions changed (any source: pad, agent — R8). */
  onRotationChange?: (dirs: RotateDirection[]) => void
  /** Selection count changed (any source: tools, agent, clear). */
  onSelectionChange?: (count: number) => void
  /** Fires on any manual viewport/keyboard input (agent pause trigger, R14). */
  onManualInput?: () => void
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

const ViewerCanvas = forwardRef<ViewerHandle, ViewerCanvasProps>(
  function ViewerCanvas({ onStateChange, onMovementChange, onRotationChange, onSelectionChange, onManualInput }, ref) {
    const containerRef = useRef<HTMLDivElement>(null)
    const managerRef = useRef<SceneManager | null>(null)
    const [isDragging, setIsDragging] = useState(false)

    /* ---- Expose ViewerHandle via ref ---- */

    useImperativeHandle(ref, () => {
      // The manager is created synchronously in useEffect below, but the
      // imperative handle may be read before that. Return a lazy proxy
      // that delegates to the current manager instance.
      const mgr = () => managerRef.current!

      return {
        setCameraPose: (...a) => mgr().setCameraPose(...a),
        getCameraPose: () => mgr().getCameraPose(),
        lookAt: (...a) => mgr().lookAt(...a),
        setView: (...a) => mgr().setView(...a),
        orbit: (...a) => mgr().orbit(...a),
        dolly: (...a) => mgr().dolly(...a),
        captureFrame: () => mgr().captureFrame(),
        getOverlayGroup: () => mgr().getOverlayGroup(),
        getCamera: () => mgr().getCamera(),
        getRenderer: () => mgr().getRenderer(),
        renderOnce: () => mgr().renderOnce(),
        getSplatCount: () => mgr().getSplatCount(),
        getBoundingBox: () => mgr().getBoundingBox(),
        getSceneCore: () => mgr().getSceneCore(),
        getSceneRevision: () => mgr().getSceneRevision(),
        isLoaded: () => mgr().isLoaded(),
        loadSplat: (url) => mgr().loadSplat(url),
        loadSplatFile: (file) => mgr().loadSplatFile(file),
        cleanOpacity: (t) => mgr().cleanOpacity(t),
        removeOutliers: (...a) => mgr().removeOutliers(...a),
        cropBbox: (...a) => mgr().cropBbox(...a),
        filterByScale: (...a) => mgr().filterByScale(...a),
        filterByColor: (...a) => mgr().filterByColor(...a),
        filterByDensity: (...a) => mgr().filterByDensity(...a),
        filterByHeight: (...a) => mgr().filterByHeight(...a),
        getNavigationMode: () => mgr().getNavigationMode(),
        setNavigationMode: (m) => mgr().setNavigationMode(m),
        setMovementInput: (d, a) => mgr().setMovementInput(d, a),
        getActiveDirections: () => mgr().getActiveDirections(),
        setRotationInput: (d, a) => mgr().setRotationInput(d, a),
        getActiveRotations: () => mgr().getActiveRotations(),
        getLiveIds: () => mgr().getLiveIds(),
        deleteByIds: (ids) => mgr().deleteByIds(ids),
        keepOnlyIds: (ids) => mgr().keepOnlyIds(ids),
        getCentersWorld: () => mgr().getCentersWorld(),
        setIdMapFromIds: (ids) => mgr().setIdMapFromIds(ids),
        getSelectionIds: () => mgr().getSelectionIds(),
        getSelectionCount: () => mgr().getSelectionCount(),
        updateSelection: (ids, mode) => mgr().updateSelection(ids, mode),
        clearSelection: () => mgr().clearSelection(),
        invertSelection: () => mgr().invertSelection(),
        getSelectionSummary: () => mgr().getSelectionSummary(),
        deleteSelection: () => mgr().deleteSelection(),
        keepSelection: () => mgr().keepSelection(),
        showSelectionPreview: (s, c, z) => mgr().showSelectionPreview(s, c, z),
        clearSelectionPreview: () => mgr().clearSelectionPreview(),
        getSceneStats: () => mgr().getSceneStats(),
        undo: () => mgr().undo(),
        canUndo: () => mgr().canUndo(),
        getUndoStackLabels: () => mgr().getUndoStackLabels(),
      } satisfies ViewerHandle
    })

    /* ---- Lifecycle: create / destroy SceneManager ---- */

    useEffect(() => {
      const container = containerRef.current
      if (!container) return

      const manager = new SceneManager()
      manager.onStateChange = onStateChange ?? null
      manager.mount(container)
      managerRef.current = manager

      return () => {
        manager.unmount()
        managerRef.current = null
      }
      // onStateChange is intentionally excluded to avoid re-creating the
      // manager on every render; we update the callback below instead.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    /* Keep the onStateChange callback in sync without re-mounting */
    useEffect(() => {
      if (managerRef.current) {
        managerRef.current.onStateChange = onStateChange ?? null
      }
    }, [onStateChange])

    useEffect(() => {
      if (managerRef.current) {
        managerRef.current.onMovementChange = onMovementChange ?? null
      }
    }, [onMovementChange])

    useEffect(() => {
      if (managerRef.current) {
        managerRef.current.onRotationChange = onRotationChange ?? null
      }
    }, [onRotationChange])

    useEffect(() => {
      if (managerRef.current) {
        managerRef.current.onSelectionChange = onSelectionChange ?? null
      }
    }, [onSelectionChange])

    /* WASD/QE keyboard → the same movement input the pad and agent use */
    useEffect(() => {
      const isTyping = (e: KeyboardEvent): boolean => {
        const t = e.target as HTMLElement | null
        return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      }
      const down = (e: KeyboardEvent) => {
        if (e.repeat || isTyping(e)) return
        const dir = KEY_TO_DIRECTION[e.code]
        if (!dir) return
        onManualInput?.()
        managerRef.current?.setMovementInput(dir, true)
      }
      const up = (e: KeyboardEvent) => {
        const dir = KEY_TO_DIRECTION[e.code]
        if (!dir || isTyping(e)) return
        managerRef.current?.setMovementInput(dir, false)
      }
      window.addEventListener('keydown', down)
      window.addEventListener('keyup', up)
      return () => {
        window.removeEventListener('keydown', down)
        window.removeEventListener('keyup', up)
      }
    }, [onManualInput])

    /* ---- Drag-and-drop ---- */

    const onDragOver = useCallback((e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragging(true)
    }, [])

    const onDragLeave = useCallback((e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragging(false)
    }, [])

    const onDrop = useCallback(
      (e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragging(false)

        const file = e.dataTransfer.files[0]
        if (!file) return

        const name = file.name.toLowerCase()
        if (name.endsWith('.ply') || name.endsWith('.splat') || name.endsWith('.spz') || name.endsWith('.ksplat')) {
          managerRef.current?.loadSplatFile(file)
        }
      },
      [],
    )

    /* ---- Render ---- */

    return (
      <div
        ref={containerRef}
        className="w-full h-full relative"
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        {isDragging && (
          <div
            className="absolute inset-0 z-50 flex items-center justify-center bg-black/50 border-2 border-dashed border-white/60 rounded-lg pointer-events-none"
          >
            <span className="text-white text-lg font-medium">
              Drop .ply or .splat file
            </span>
          </div>
        )}
      </div>
    )
  },
)

export default ViewerCanvas
