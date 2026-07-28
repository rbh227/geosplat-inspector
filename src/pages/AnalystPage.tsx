import { useEffect, useState } from 'react'
import ViewerCanvas from '../viewer/ViewerCanvas'
import ViewerErrorBoundary from '../ui/ViewerErrorBoundary'
import ChatPanel from '../ui/ChatPanel'
import NarrationBar from '../ui/NarrationBar'
import MovePad from '../ui/MovePad'
import RotatePad from '../ui/RotatePad'
import EmptyState from '../ui/EmptyState'
import { useSession } from '../session/useSession'
import { analystStatus } from './analystStatus'

/**
 * Look-only analyst window. Opened from the editor with a scene id, it loads
 * that scene's CURRENT alive set — i.e. whatever the editor left behind after
 * cleanup — and runs the agent in the Understand stage. No tool rail, no
 * selection, no history, no export: the backend enforces look-only at the
 * spec and dispatch level, and this window simply has no editing surface.
 */
export default function AnalystPage({ sceneId }: { sceneId: string | null }) {
  // restoreOnMount: false — the analyst's scene comes from its URL, not from
  // the editor's sessionStorage record (which is per-tab anyway).
  const session = useSession({ stage: 'understand', restoreOnMount: false })
  const {
    viewerRef, viewerState, hasScene, status: toast, narration, messages,
    isThinking, agentPaused, loadBackendScene, loadFile, send, stop, resume,
    onManualInput, onViewerStateChange, onMovementChange, onRotationChange,
    activeDirections, activeRotations,
  } = session

  // Tracks WHICH scene failed rather than a bare boolean, so the flag is
  // derived during render instead of reset by a synchronous setState in the
  // effect (react-hooks/set-state-in-effect).
  const [failedSceneId, setFailedSceneId] = useState<string | null>(null)

  useEffect(() => {
    if (!sceneId) return
    void loadBackendScene(sceneId).catch(() => setFailedSceneId(sceneId))
  }, [sceneId, loadBackendScene])

  const gone = failedSceneId !== null && failedSceneId === sceneId
  const state = analystStatus(sceneId, gone)

  return (
    <div className="w-screen h-screen flex flex-col overflow-hidden bg-bg-deep">
      <div className="flex items-center gap-3 border-b border-border-mid px-4 py-2">
        <span className="font-mono text-sm text-white/85">Scene Analyst</span>
        <span className="rounded-[2px] bg-white/10 px-1.5 font-mono text-[10px] leading-[16px] text-white/60">
          look-only
        </span>
        <span className="ml-auto font-mono text-[11px] text-white/35">
          {viewerState.splatCount > 0
            ? `${viewerState.splatCount.toLocaleString()} splats`
            : ''}
        </span>
      </div>

      <div className="flex-1 flex min-h-0">
        <div className="flex-1 min-w-0 flex flex-col bg-bg-deep">
          <div className="flex-1 relative overflow-hidden">
            <ViewerErrorBoundary>
              <ViewerCanvas
                ref={viewerRef}
                onStateChange={onViewerStateChange}
                onMovementChange={onMovementChange}
                onRotationChange={onRotationChange}
                onManualInput={onManualInput}
              />
            </ViewerErrorBoundary>

            {/* Movement pads light for ANY input source, including the agent —
                this is how the operator watches it maneuver. */}
            {state === 'ready' && hasScene && (
              <div className="absolute bottom-3 right-3 z-20 flex items-end gap-2">
                <RotatePad
                  activeRotations={activeRotations}
                  onInput={(dir, active) => {
                    if (active) onManualInput()
                    viewerRef.current?.setRotationInput(dir, active)
                  }}
                />
                <MovePad
                  activeDirections={activeDirections}
                  onInput={(dir, active) => {
                    if (active) onManualInput()
                    viewerRef.current?.setMovementInput(dir, active)
                  }}
                />
              </div>
            )}

            {agentPaused && (
              <div className="absolute top-3 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 rounded border border-amber-400/40 bg-black/80 px-3 py-1.5">
                <span className="font-mono text-xs text-amber-200/90">
                  Agent paused — you have control
                </span>
                <button
                  type="button"
                  onClick={resume}
                  className="rounded border border-white/25 bg-white/10 px-2 py-0.5 font-mono text-[11px] text-white hover:bg-white/20 cursor-pointer"
                >
                  Resume
                </button>
                <button
                  type="button"
                  onClick={stop}
                  className="rounded border border-red-400/30 bg-red-500/10 px-2 py-0.5 font-mono text-[11px] text-red-200 hover:bg-red-500/20 cursor-pointer"
                >
                  Stop run
                </button>
              </div>
            )}

            {!agentPaused && toast && (
              <div className="absolute top-3 left-1/2 z-30 -translate-x-1/2 rounded border border-white/20 bg-black/70 px-3 py-1.5 font-mono text-xs text-white/90">
                {toast}
              </div>
            )}

            {/* Scenes are in-memory only, so a restarted backend loses them
                while this window still holds the id. Say so and offer a way
                forward — never a hung spinner. */}
            {state === 'scene-gone' && (
              <div className="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-black/85 px-6 text-center">
                <p className="font-mono text-sm text-amber-200/90">
                  That scene is no longer loaded on the backend.
                </p>
                <p className="max-w-md font-mono text-xs text-white/50">
                  Scenes live in memory only, so restarting the backend clears
                  them. Re-open this window from the editor, or drop a .ply here
                  to analyze it directly.
                </p>
                <div className="relative h-48 w-full max-w-md">
                  <EmptyState onImport={() => {}} onDropFile={loadFile} />
                </div>
              </div>
            )}

            {state === 'no-scene' && (
              <EmptyState onImport={() => {}} onDropFile={loadFile} />
            )}
          </div>
          <NarrationBar state={viewerState} />
        </div>

        <ChatPanel
          isOpen
          stage="understand"
          messages={messages}
          isThinking={isThinking}
          narration={narration}
          proposal={null}
          onProposalDecide={() => {}}
          onSend={send}
          onStop={stop}
          onClose={() => {}}
        />
      </div>
    </div>
  )
}
