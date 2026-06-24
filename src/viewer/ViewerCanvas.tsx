import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  useCallback,
} from 'react'
import type { ViewerHandle, ViewerState } from '../types/viewer.ts'
import { SceneManager } from './SceneManager.ts'

/* ------------------------------------------------------------------ */
/*  Props                                                             */
/* ------------------------------------------------------------------ */

interface ViewerCanvasProps {
  onStateChange?: (state: ViewerState) => void
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

const ViewerCanvas = forwardRef<ViewerHandle, ViewerCanvasProps>(
  function ViewerCanvas({ onStateChange }, ref) {
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
