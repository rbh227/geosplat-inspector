import { useCallback, useEffect, useRef, useState } from 'react'
import type { ProposalState } from '@agent'
import {
  scenePlyUrl, isBackendLoadable, editByIds, historyOp,
  getModelConfig, type ModelConfig,
} from '../backend/client'
import { useSession } from '../session/useSession'
import { analystHref } from '../routing'
import ViewerCanvas from '../viewer/ViewerCanvas'
import SelectionOverlay, { type SelectionTool } from '../viewer/SelectionOverlay'
import ViewerErrorBoundary from '../ui/ViewerErrorBoundary'
import TopBar, { type Stage } from '../ui/TopBar'
import NarrationBar from '../ui/NarrationBar'
import ChatPanel from '../ui/ChatPanel'
import SettingsPanel from '../ui/SettingsPanel'
import EditorToolbar from '../ui/EditorToolbar'
import MovePad from '../ui/MovePad'
import RotatePad from '../ui/RotatePad'
import EmptyState from '../ui/EmptyState'
import type { DemoSplat } from '../demos'

export default function EditorPage() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [rightOpen, setRightOpen] = useState(true)

  // ── Editor state (v0.2) ──
  const [stage, setStage] = useState<Stage>('clean')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null)
  const [settingsAttention, setSettingsAttention] = useState(false)
  const [activeTool, setActiveTool] = useState<SelectionTool | null>(null)
  const [eraseMode, setEraseMode] = useState(false)
  const [selectionCount, setSelectionCount] = useState(0)
  const [cropBoxCount, setCropBoxCount] = useState(0)
  const [hasCropBox, setHasCropBox] = useState(false)
  // Set right before a crop commit tears down the gizmo (cropToBox() calls
  // endCropBox() internally on every path, including the empty/no-op ones)
  // and cleared when the 120ms poll (re)starts for a fresh session. Guards
  // the poll against re-seeding a brand-new box in the gap between the
  // commit running and React actually unmounting/clearing this effect.
  const cropCommitPendingRef = useRef(false)

  // A parked crop/edit proposal awaiting the operator's decision (or null).
  const [proposal, setProposal] = useState<ProposalState | null>(null)
  const handleProposal = useCallback((p: ProposalState | null) => setProposal(p), [])

  const session = useSession({ stage, onProposal: handleProposal })
  const {
    viewerRef, viewerState, hasScene, backendSceneId, baselineCount, sceneIdRef,
    reloadAuthoritative, showStatus, status, isThinking, agentPaused,
    viewingOriginal, showVersion,
  } = session

  // Model picker (in-app settings): fetch the current selection once on mount
  // and nudge the gear icon if nothing usable is configured yet. The app is
  // fully usable without a model — this is a hint, not a gate.
  useEffect(() => {
    let cancelled = false
    void getModelConfig().then((cfg) => {
      if (cancelled) return
      setModelConfig(cfg)
      if (cfg && !cfg.key_set) {
        setSettingsAttention(true)
        showStatus('No AI model set up yet — click the gear to choose one')
      }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [showStatus])

  const handleSelectionChange = useCallback((count: number) => {
    setSelectionCount(count)
  }, [])

  /** Escape with no gesture in progress lands in pointer mode (R6/KTD5). */
  const handleExitTool = useCallback(() => {
    setActiveTool(null)
  }, [])

  // ── Selection actions: optimistic local apply + backend record (KTD2) ──
  // The backend is the source of truth; a failed call reloads its scene.
  const commitEdit = useCallback((op: 'delete_by_ids' | 'keep_only_ids', ids: Uint32Array) => {
    if (ids.length === 0) return
    const sceneId = sceneIdRef.current
    if (!sceneId) {
      // view-only scene: local edit stands alone — and blocks a transparent
      // re-upload (the original file no longer matches what's on screen)
      session.markLocalOnlyEdit()
      return
    }
    void editByIds(sceneId, op, ids).catch(async (err) => {
      console.warn('[backend] edit rejected; restoring authoritative scene:', err)
      await reloadAuthoritative(sceneId)
      showStatus('Edit rejected — scene restored')
    })
  }, [reloadAuthoritative, showStatus, sceneIdRef, session])

  const handleDeleteSelection = useCallback(() => {
    const ids = viewerRef.current?.deleteSelection() ?? new Uint32Array(0)
    commitEdit('delete_by_ids', ids)
  }, [commitEdit, viewerRef])

  /** Entering erase mode clears the selection so each gesture deletes only
   *  its own hits — one gesture, one undo step (KTD3). */
  const handleEraseModeChange = useCallback((on: boolean) => {
    setEraseMode(on)
    if (on) setSelectionCount(viewerRef.current?.clearSelection() ?? 0)
  }, [viewerRef])

  const handleKeepSelection = useCallback(() => {
    const ids = viewerRef.current?.keepSelection() ?? new Uint32Array(0)
    commitEdit('keep_only_ids', ids)
  }, [commitEdit, viewerRef])

  const handleCropToBox = useCallback(() => {
    const before = viewerRef.current?.getSplatCount() ?? 0
    cropCommitPendingRef.current = true
    const ids = viewerRef.current?.cropToBox() ?? new Uint32Array(0)
    if (ids.length === 0) {
      // cropToBox() already ended the session (endCropBox()) — the tool
      // button must not read as active with no gizmo left to resume it.
      showStatus('Box contains no splats — nothing cropped')
      setActiveTool(null)
      return
    }
    if (ids.length === before) {
      // Everything was already inside: a keep_only_ids here is a no-op that still
      // costs a history entry, so the operator's Undo would appear to do nothing.
      showStatus('Box already contains the whole scene — nothing to crop')
      setActiveTool(null)
      return
    }
    commitEdit('keep_only_ids', ids)
    setActiveTool(null)
  }, [commitEdit, showStatus, viewerRef])

  // Crop-box tool lifecycle: start/stop the gizmo with the tool, polling the
  // count while active (the gizmo mutates the box on drag, outside React).
  //
  // Re-seed on a stranded reload: a reload while the tool is active — Redo, a
  // failed-edit rollback, or an agent scene_changed reload — disposes and
  // rebuilds the splat mesh, which tears down the gizmo. None of those reload
  // paths change `activeTool`, so this effect would not otherwise re-run. The
  // existing 120ms poll already touches the viewer on a cadence that isn't the
  // render loop, so it's a natural place to detect `getCropBox() === null`
  // (session torn down, tool still selected) and re-seed against the fresh
  // scene.
  useEffect(() => {
    const viewer = viewerRef.current
    if (activeTool !== 'cropBox') {
      viewer?.endCropBox()
      return
    }
    cropCommitPendingRef.current = false
    viewer?.beginCropBox()
    setHasCropBox(viewer?.getCropBox() !== null)
    const id = window.setInterval(() => {
      if (cropCommitPendingRef.current) return
      if (viewer?.getCropBox() === null) {
        viewer?.beginCropBox()
      }
      setCropBoxCount(viewer?.cropBoxCount() ?? 0)
      setHasCropBox(viewer?.getCropBox() !== null)
    }, 120)
    return () => {
      window.clearInterval(id)
      viewer?.endCropBox()
      setCropBoxCount(0)
      setHasCropBox(false)
    }
  }, [activeTool, viewerRef])

  // v0.6: while a `crop_outside_box` proposal is parked, hand the operator an
  // editable copy of the box the agent previewed (cyan gizmo, same channel as
  // the manual crop-box tool above) so their approval binds to the box they
  // actually looked at, not the one the model chose. The amber proposal
  // wireframe (`showProposalBox`, the agent's own record) is untouched — this
  // seeds a second, independent overlay on top of it and the two diverge as
  // the operator drags. Detach as soon as the proposal resolves or changes
  // kind; ws-client reads the live box back via `getCropBox()`.
  useEffect(() => {
    const viewer = viewerRef.current
    if (proposal?.kind === 'crop_outside_box') {
      const box = viewer?.getProposalBox()
      if (box) viewer?.beginCropBox(box)
    } else {
      viewer?.endCropBox()
    }
  }, [proposal, viewerRef])

  const handleInvertSelection = useCallback(() => {
    setSelectionCount(viewerRef.current?.invertSelection() ?? 0)
  }, [viewerRef])

  const handleClearSelection = useCallback(() => {
    setSelectionCount(viewerRef.current?.clearSelection() ?? 0)
  }, [viewerRef])

  // Undo/redo: the local stack answers instantly (camera preserved); the
  // backend History records the same sequence and stays authoritative.
  const handleUndo = useCallback(() => {
    const localOk = viewerRef.current?.undo() ?? false
    const sceneId = sceneIdRef.current
    if (!sceneId) return
    void historyOp(sceneId, 'undo').then(async (res) => {
      if (!localOk && res.ok) await reloadAuthoritative(sceneId) // backend-only history
    }).catch((err) => console.warn('[backend] undo failed:', err))
  }, [reloadAuthoritative, sceneIdRef, viewerRef])

  const handleRedo = useCallback(() => {
    const sceneId = sceneIdRef.current
    if (!sceneId) return
    void historyOp(sceneId, 'redo').then(async (res) => {
      if (res.ok) await reloadAuthoritative(sceneId)
    }).catch((err) => console.warn('[backend] redo failed:', err))
  }, [reloadAuthoritative, sceneIdRef])

  const handleResetView = useCallback(() => {
    viewerRef.current?.setView('front', true)
  }, [viewerRef])

  const handleNavModeToggle = useCallback(() => {
    const v = viewerRef.current
    if (!v) return
    v.setNavigationMode(v.getNavigationMode() === 'fly' ? 'orbit' : 'fly')
  }, [viewerRef])

  const handleImport = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  /** Download the backend's live scene — the edited alive set (R9/KTD7).
   *  The source file on disk is never modified; this serves the edited copy. */
  const handleExport = useCallback(() => {
    if (!backendSceneId) return
    const a = document.createElement('a')
    a.href = scenePlyUrl(backendSceneId)
    a.download = ''
    document.body.appendChild(a)
    a.click()
    a.remove()
  }, [backendSceneId])

  const removedCount = Math.max(0, baselineCount - viewerState.splatCount)

  const handleFileSelected = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) session.loadFile(file)
    e.target.value = ''
  }, [session])

  const handleLoadDemo = useCallback(async (demo: DemoSplat) => {
    if (!isBackendLoadable(demo.file)) {
      session.loadUrl(demo.url, demo.name)
      return
    }
    try {
      const res = await fetch(demo.url)
      if (!res.ok) throw new Error(`fetch ${demo.url} → ${res.status}`)
      const blob = await res.blob()
      session.loadFile(new File([blob], demo.file))
    } catch (err) {
      console.warn('[load]', err)
      showStatus(`Couldn't load ${demo.name}`)
    }
  }, [session, showStatus])

  // Understand is look-only (R15): leaving Clean drops any active tool/selection.
  const handleStageChange = useCallback((next: Stage) => {
    if (isThinking) return // switcher is disabled during a run (AE2 guard)
    if (next === 'understand') {
      setActiveTool(null)
      setEraseMode(false)
      viewerRef.current?.clearSelection()
      setSelectionCount(0)
    }
    setStage(next)
  }, [isThinking, viewerRef])

  // Editing is refused while the original upload is on screen: the stable ID
  // map is indexed against the EDITED alive set, so an edit made against the
  // original's packing would silently desync the frontend from the backend.
  const editingEnabled = stage === 'clean' && !viewingOriginal

  return (
    <div className="w-screen h-screen flex flex-col overflow-hidden bg-bg-deep">
      {/* Hidden file input for Import button */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".ply,.splat,.spz,.ksplat"
        className="hidden"
        onChange={handleFileSelected}
      />

      {/* Top bar */}
      <TopBar
        stage={stage}
        onStageChange={handleStageChange}
        stageLocked={isThinking}
        navigationMode={viewerState.navigationMode}
        onToggleNavMode={handleNavModeToggle}
        rightOpen={rightOpen}
        onToggleRight={() => setRightOpen((p) => !p)}
        settingsOpen={settingsOpen}
        onToggleSettings={() => {
          setSettingsOpen((p) => !p)
          setSettingsAttention(false)
        }}
        settingsAttention={settingsAttention}
        onImport={handleImport}
        onLoadDemo={handleLoadDemo}
        onResetView={handleResetView}
        canExport={backendSceneId !== null}
        removedCount={removedCount}
        onExport={handleExport}
        canAnalyze={backendSceneId !== null}
        onAnalyze={() => {
          if (backendSceneId) {
            window.open(analystHref(backendSceneId), '_blank', 'noopener')
          }
        }}
        canCompare={backendSceneId !== null}
        viewingOriginal={viewingOriginal}
        onShowVersion={(v) => { void showVersion(v) }}
      />

      {/* Body: viewport + right panel */}
      <div className="flex-1 flex min-h-0">
        {/* Center: Viewport + Narration */}
        <div className="flex-1 min-w-0 flex flex-col bg-bg-deep">
          <div className="flex-1 relative overflow-hidden">
            <ViewerErrorBoundary>
              <ViewerCanvas
                ref={viewerRef}
                onStateChange={session.onViewerStateChange}
                onMovementChange={session.onMovementChange}
                onRotationChange={session.onRotationChange}
                onSelectionChange={handleSelectionChange}
                onManualInput={session.onManualInput}
              />
            </ViewerErrorBoundary>

            {/* Selection interaction layer (Clean stage only) */}
            {hasScene && editingEnabled && (
              <SelectionOverlay
                viewerRef={viewerRef}
                tool={activeTool}
                onSelectionChange={handleSelectionChange}
                onManualInput={session.onManualInput}
                onExitTool={handleExitTool}
                eraseMode={eraseMode}
                onGestureCommit={handleDeleteSelection}
              />
            )}

            {/* Left tool rail (Clean stage only — Understand is look-only) */}
            {hasScene && editingEnabled && (
              <EditorToolbar
                activeTool={activeTool}
                onToolChange={setActiveTool}
                eraseMode={eraseMode}
                onEraseModeChange={handleEraseModeChange}
                selectionCount={selectionCount}
                onDeleteSelection={handleDeleteSelection}
                onKeepSelection={handleKeepSelection}
                onInvertSelection={handleInvertSelection}
                onClearSelection={handleClearSelection}
                onUndo={handleUndo}
                onRedo={handleRedo}
                cropBoxCount={cropBoxCount}
                hasCropBox={hasCropBox}
                onCropToBox={handleCropToBox}
              />
            )}

            {/* Rotate + WASD movement pads — every input source lights them
                (R8/R13); a shared flex container declares their layout. */}
            {hasScene && (
              <div className="absolute bottom-3 right-3 z-20 flex items-end gap-2">
                <RotatePad
                  activeRotations={session.activeRotations}
                  onInput={(dir, active) => {
                    if (active) session.onManualInput()
                    viewerRef.current?.setRotationInput(dir, active)
                  }}
                />
                <MovePad
                  activeDirections={session.activeDirections}
                  onInput={(dir, active) => {
                    if (active) session.onManualInput()
                    viewerRef.current?.setMovementInput(dir, active)
                  }}
                />
              </div>
            )}

            {/* Awaiting-review banner: while a proposal is parked the run is
                blocked on the operator — inspect freely, decide in the card. */}
            {proposal && (
              <div className="absolute top-3 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 rounded border border-amber-400/40 bg-black/80 px-3 py-1.5">
                <span className="font-mono text-xs text-amber-200/90">
                  Awaiting your review
                </span>
                <button
                  type="button"
                  onClick={session.stop}
                  className="rounded border border-red-400/30 bg-red-500/10 px-2 py-0.5 font-mono text-[11px] text-red-200 hover:bg-red-500/20 cursor-pointer"
                >
                  Stop run
                </button>
              </div>
            )}

            {/* Pause banner: persists until Resume or Stop — never self-dismisses.
                Manual edits during pause are allowed and share the history. */}
            {!proposal && agentPaused && (
              <div className="absolute top-3 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 rounded border border-amber-400/40 bg-black/80 px-3 py-1.5">
                <span className="font-mono text-xs text-amber-200/90">
                  Agent paused — you have control
                </span>
                <button
                  type="button"
                  onClick={session.resume}
                  className="rounded border border-white/25 bg-white/10 px-2 py-0.5 font-mono text-[11px] text-white hover:bg-white/20 cursor-pointer"
                >
                  Resume
                </button>
                <button
                  type="button"
                  onClick={session.stop}
                  className="rounded border border-red-400/30 bg-red-500/10 px-2 py-0.5 font-mono text-[11px] text-red-200 hover:bg-red-500/20 cursor-pointer"
                >
                  Stop run
                </button>
              </div>
            )}

            {/* Viewing the upload: say so, and say the edits are safe. */}
            {viewingOriginal && (
              <div className="absolute top-3 left-1/2 z-30 flex -translate-x-1/2 items-center gap-3 rounded border border-sky-400/40 bg-black/80 px-3 py-1.5">
                <span className="font-mono text-xs text-sky-200/90">
                  Original upload — editing disabled, your edits are kept
                </span>
                <button
                  type="button"
                  onClick={() => { void showVersion('current') }}
                  className="rounded border border-white/25 bg-white/10 px-2 py-0.5 font-mono text-[11px] text-white hover:bg-white/20 cursor-pointer"
                >
                  Back to Edited
                </button>
              </div>
            )}

            {/* Transient status (edit rejected, etc.) */}
            {!agentPaused && !proposal && !viewingOriginal && status && (
              <div className="absolute top-3 left-1/2 z-30 -translate-x-1/2 rounded border border-white/20 bg-black/70 px-3 py-1.5 font-mono text-xs text-white/90">
                {status}
              </div>
            )}

            {/* Empty state: shown until a scene is loaded */}
            {!hasScene && (
              <EmptyState
                onImport={handleImport}
                onDropFile={session.loadFile}
              />
            )}
          </div>
          <NarrationBar state={viewerState} />
        </div>

        {/* Right: settings takes priority over chat when both would show
            (same 380px slot — settings is a modal-like task, not a second panel). */}
        {settingsOpen ? (
          <SettingsPanel
            isOpen={settingsOpen}
            config={modelConfig}
            onClose={() => setSettingsOpen(false)}
            onSaved={(cfg) => {
              setModelConfig(cfg)
              setSettingsAttention(!cfg.key_set)
            }}
          />
        ) : rightOpen && (
          <ChatPanel
            isOpen={rightOpen}
            stage={stage}
            messages={session.messages}
            isThinking={isThinking}
            narration={session.narration}
            proposal={proposal}
            onProposalDecide={session.decideProposal}
            onSend={session.send}
            onStop={session.stop}
            onClose={() => setRightOpen(false)}
          />
        )}
      </div>
    </div>
  )
}
