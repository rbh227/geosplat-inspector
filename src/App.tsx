import { useCallback, useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import type { MoveDirection, RotateDirection, ViewerState, ViewerHandle } from './types/viewer'
import type { ChatMessage, AgentAction } from './types/agent'
import { createAgent, WebSocketTransport, PanelBus } from '@agent'
import type { Agent, TraceEntry, ProposalState } from '@agent'
import {
  uploadScene, runAgent, sceneWsUrl, scenePlyUrl, isBackendLoadable,
  editByIds, historyOp, getAliveIds, getSkills, type SkillInfo,
  getModelConfig, type ModelConfig,
} from './backend/client'
import { makeRendererBridge } from './backend/bridge'
import { classifyAction, completeContent } from './backend/trace'
import {
  savePersistedScene, loadPersistedScene, clearPersistedScene, updatePersistedCamera,
} from './persistence'
import ViewerCanvas from './viewer/ViewerCanvas'
import SelectionOverlay, { type SelectionTool } from './viewer/SelectionOverlay'
import ViewerErrorBoundary from './ui/ViewerErrorBoundary'
import TopBar, { type Stage } from './ui/TopBar'
import NarrationBar from './ui/NarrationBar'
import ChatPanel from './ui/ChatPanel'
import SettingsPanel from './ui/SettingsPanel'
import EditorToolbar from './ui/EditorToolbar'
import MovePad from './ui/MovePad'
import RotatePad from './ui/RotatePad'
import EmptyState from './ui/EmptyState'
import type { DemoSplat } from './demos'

const DEFAULT_VIEWER_STATE: ViewerState = {
  splatCount: 0,
  fps: 0,
  cameraPosition: [0, 0, 0],
  fileName: null,
  isLoading: false,
  undoCount: 0,
  navigationMode: 'orbit',
}

export default function App() {
  const viewerRef = useRef<ViewerHandle>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [viewerState, setViewerState] = useState<ViewerState>(DEFAULT_VIEWER_STATE)
  const [rightOpen, setRightOpen] = useState(true)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isThinking, setIsThinking] = useState(false)
  const [narration, setNarration] = useState('')
  const [agentStep, setAgentStep] = useState(0)
  // Start "has scene" true when a persisted record exists so the restore effect
  // shows the viewport (not the empty state) without a synchronous setState.
  const [hasScene, setHasScene] = useState(() => loadPersistedScene() !== null)

  // ── Editor state (v0.2) ──
  const [stage, setStage] = useState<Stage>('clean')
  const [skills, setSkills] = useState<SkillInfo[]>([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null)
  const [settingsAttention, setSettingsAttention] = useState(false)
  const [activeTool, setActiveTool] = useState<SelectionTool | null>(null)
  const [eraseMode, setEraseMode] = useState(false)
  const [selectionCount, setSelectionCount] = useState(0)
  const [activeDirections, setActiveDirections] = useState<ReadonlySet<MoveDirection>>(new Set())
  const [activeRotations, setActiveRotations] = useState<ReadonlySet<RotateDirection>>(new Set())
  const [status, setStatus] = useState<string | null>(null)
  const statusTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Edit-aware export (R9-R11/KTD6) ──
  // backendSceneId mirrors sceneIdRef into React state: registration resolves
  // async after first render, and a ref alone would never re-enable the button.
  const [backendSceneId, setBackendSceneId] = useState<string | null>(null)
  // Alive count snapshotted from the viewer handle right after load resolves;
  // removedCount derives from the live count, so undo/redo/reload stay correct.
  const [baselineCount, setBaselineCount] = useState(0)

  /** Transient status toast (e.g. "Edit rejected — scene restored"). */
  const showStatus = useCallback((text: string) => {
    setStatus(text)
    if (statusTimer.current) clearTimeout(statusTimer.current)
    statusTimer.current = setTimeout(() => setStatus(null), 4000)
  }, [])

  // ── Backend agent session (lazy: built on first send, rebuilt per scene) ──
  const agentRef = useRef<Agent | null>(null)
  const transportRef = useRef<WebSocketTransport | null>(null)
  const panelsRef = useRef<PanelBus | null>(null)
  const sceneIdRef = useRef<string | null>(null)
  const hasSceneRef = useRef(false) // mirrors hasScene for stale-closure-free reads
  // Large real-world scenes can take up to ~60s to upload+parse on the backend
  // (confirmed: 675MB/3M-gaussian scene ≈ 60s). Without this, a prompt typed
  // during that window sees sceneId===null and wrongly reports "view-only".
  const registeringSceneRef = useRef(false)
  const stageRef = useRef<Stage>('clean') // mirrors stage for stable handleSend
  const unsubsRef = useRef<Array<() => void>>([])
  const processedTraceRef = useRef(0)
  const runActionsRef = useRef<AgentAction[]>([])

  // A parked crop/edit proposal awaiting the operator's decision (or null).
  const [proposal, setProposal] = useState<ProposalState | null>(null)
  // Mirrors `proposal !== null` for stale-closure-free reads in handleManualInput.
  const proposalPendingRef = useRef(false)
  // Fold the proposal signal into React state + the ref (stable identity so the
  // per-scene ensureAgent memo stays intact).
  const handleProposalSignal = useCallback((p: ProposalState | null) => {
    setProposal(p)
    proposalPendingRef.current = p !== null
  }, [])

  const disposeAgent = useCallback(() => {
    unsubsRef.current.forEach((fn) => fn())
    unsubsRef.current = []
    agentRef.current?.dispose()
    agentRef.current = null
    transportRef.current = null
    panelsRef.current = null
    processedTraceRef.current = 0
    // Drop any parked proposal from the torn-down scene so no stale card lingers.
    proposalPendingRef.current = false
    setProposal(null)
  }, [])

  useEffect(() => disposeAgent, [disposeAgent])
  useEffect(() => { hasSceneRef.current = hasScene }, [hasScene])

  // ── Refresh persistence (Bug 1) ──
  // On mount, restore the last backend scene if it still exists. Probe /ids
  // first (cheap JSON, 404s when the backend has lost the scene) so a stale
  // record falls back to the empty state instead of a hung load.
  useEffect(() => {
    const rec = loadPersistedScene()
    if (!rec) return
    let cancelled = false
    void (async () => {
      try {
        const ids = await getAliveIds(rec.sceneId)
        if (cancelled) return
        await viewerRef.current?.loadSplat(scenePlyUrl(rec.sceneId))
        viewerRef.current?.setIdMapFromIds(ids)
        sceneIdRef.current = rec.sceneId
        setBackendSceneId(rec.sceneId)
        setBaselineCount(rec.baseline)
        if (rec.camera) {
          viewerRef.current?.setCameraPose(
            new THREE.Vector3(...rec.camera.position),
            new THREE.Vector3(...rec.camera.target),
            false, // no tween: land exactly where the user left off, over auto-framing
          )
        }
      } catch (err) {
        console.warn('[persistence] scene restore failed; starting fresh:', err)
        clearPersistedScene()
        if (!cancelled) {
          setHasScene(false)
          setBackendSceneId(null)
          sceneIdRef.current = null
        }
      }
    })()
    return () => { cancelled = true }
  }, [])

  // Persist the latest camera pose as the page unloads, so a refresh lands the
  // user exactly where they were (pagehide is more bfcache-friendly than unload).
  useEffect(() => {
    const onHide = () => {
      if (!sceneIdRef.current) return
      const pose = viewerRef.current?.getCameraPose()
      if (!pose) return
      updatePersistedCamera({
        position: [pose.position.x, pose.position.y, pose.position.z],
        target: [pose.target.x, pose.target.y, pose.target.z],
      })
    }
    window.addEventListener('pagehide', onHide)
    return () => window.removeEventListener('pagehide', onHide)
  }, [])

  // One skills vocabulary, two invokers (R11): fetched per stage, shown as
  // clickable entries, and rendered into the agent's system prompt backend-side.
  useEffect(() => {
    let cancelled = false
    void getSkills(stage).then((list) => {
      if (!cancelled) setSkills(list)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [stage])

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

  const handleStateChange = useCallback((state: ViewerState) => {
    setViewerState(state)
  }, [])

  const handleMovementChange = useCallback((dirs: MoveDirection[]) => {
    setActiveDirections(new Set(dirs))
  }, [])

  const handleRotationChange = useCallback((dirs: RotateDirection[]) => {
    setActiveRotations(new Set(dirs))
  }, [])

  const handleSelectionChange = useCallback((count: number) => {
    setSelectionCount(count)
  }, [])

  /** Escape with no gesture in progress lands in pointer mode (R6/KTD5). */
  const handleExitTool = useCallback(() => {
    setActiveTool(null)
  }, [])

  const [agentPaused, setAgentPaused] = useState(false)
  const isThinkingRef = useRef(false)
  const agentPausedRef = useRef(false)
  useEffect(() => { isThinkingRef.current = isThinking }, [isThinking])
  useEffect(() => { agentPausedRef.current = agentPaused }, [agentPaused])

  const sendPauseSignal = useCallback((type: 'agent_pause' | 'agent_resume') => {
    transportRef.current?.send({ type, id: `${type}-${Date.now()}`, payload: {} })
  }, [])

  /** Manual input during an agent run pauses it at the next tool-call
   *  boundary (R14/AE1). The banner persists until Resume or Stop.
   *  Exception: while a proposal is parked, camera inspection is expected
   *  review behavior, so it must NOT pause the (already-blocked) run. */
  const handleManualInput = useCallback(() => {
    if (isThinkingRef.current && !agentPausedRef.current && !proposalPendingRef.current) {
      sendPauseSignal('agent_pause')
      setAgentPaused(true)
    }
  }, [sendPauseSignal])

  const handleResumeAgent = useCallback(() => {
    sendPauseSignal('agent_resume')
    setAgentPaused(false)
  }, [sendPauseSignal])

  const handleStopAgent = useCallback(() => {
    // Resolve any parked proposal first so the blocked loop unwinds before the
    // interrupt (the resolver latch makes this safe even if already resolved).
    panelsRef.current?.proposal.get()?.resolve('rejected', 'operator stopped the run')
    transportRef.current?.send({ type: 'user_interrupt', id: `int-${Date.now()}`, payload: {} })
    // release the paused loop so it can observe the abort
    sendPauseSignal('agent_resume')
    setAgentPaused(false)
  }, [sendPauseSignal])

  /** Operator decision on the parked proposal — resolves via the signal's
   *  latched resolver (Task 10), which sends the reply and clears the signal. */
  const handleProposalDecide = useCallback(
    (verdict: 'approved' | 'rejected' | 'adjusted', feedback?: string) => {
      panelsRef.current?.proposal.get()?.resolve(verdict, feedback)
    },
    [],
  )

  /**
   * Reload the backend's authoritative scene and adopt its alive-ID list so
   * the viewer's stable ID map keeps matching the backend's ID space (KTD2/3).
   */
  const reloadAuthoritative = useCallback(async (sceneId: string) => {
    await viewerRef.current?.loadSplat(scenePlyUrl(sceneId))
    try {
      const ids = await getAliveIds(sceneId)
      viewerRef.current?.setIdMapFromIds(ids)
    } catch (err) {
      console.warn('[backend] alive-id adoption failed after reload:', err)
    }
  }, [])

  // Register a freshly loaded file with the backend (best-effort, .ply only).
  // A new scene means the previous agent/WS is stale, so tear it down.
  const registerScene = useCallback(async (file: File) => {
    disposeAgent()
    sceneIdRef.current = null
    setBackendSceneId(null)
    if (!isBackendLoadable(file.name)) {
      clearPersistedScene() // view-only scene: nothing restorable, drop any stale record
      return
    }
    registeringSceneRef.current = true
    setStatus('Uploading scene to backend…')
    try {
      const { id } = await uploadScene(file)
      sceneIdRef.current = id
      setBackendSceneId(id)
      // Persist for refresh-restore (Bug 1). Baseline = the just-loaded count,
      // captured from the handle (no edits yet), so the export badge stays right.
      savePersistedScene({
        sceneId: id,
        fileName: file.name,
        baseline: viewerRef.current?.getSplatCount() ?? 0,
        camera: null,
      })
      setStatus(null)
    } catch (err) {
      console.warn('[backend] scene upload failed; agent disabled for this scene:', err)
      clearPersistedScene()
      showStatus('Scene upload failed — this scene is view-only until reloaded')
    } finally {
      registeringSceneRef.current = false
    }
  }, [disposeAgent, showStatus])

  // ── Selection actions: optimistic local apply + backend record (KTD2) ──
  // The backend is the source of truth; a failed call reloads its scene.
  const commitEdit = useCallback((op: 'delete_by_ids' | 'keep_only_ids', ids: Uint32Array) => {
    if (ids.length === 0) return
    const sceneId = sceneIdRef.current
    if (!sceneId) return // view-only scene: local edit stands alone
    void editByIds(sceneId, op, ids).catch(async (err) => {
      console.warn('[backend] edit rejected; restoring authoritative scene:', err)
      await reloadAuthoritative(sceneId)
      showStatus('Edit rejected — scene restored')
    })
  }, [reloadAuthoritative, showStatus])

  const handleDeleteSelection = useCallback(() => {
    const ids = viewerRef.current?.deleteSelection() ?? new Uint32Array(0)
    commitEdit('delete_by_ids', ids)
  }, [commitEdit])

  /** Entering erase mode clears the selection so each gesture deletes only
   *  its own hits — one gesture, one undo step (KTD3). */
  const handleEraseModeChange = useCallback((on: boolean) => {
    setEraseMode(on)
    if (on) setSelectionCount(viewerRef.current?.clearSelection() ?? 0)
  }, [])

  const handleKeepSelection = useCallback(() => {
    const ids = viewerRef.current?.keepSelection() ?? new Uint32Array(0)
    commitEdit('keep_only_ids', ids)
  }, [commitEdit])

  const handleInvertSelection = useCallback(() => {
    setSelectionCount(viewerRef.current?.invertSelection() ?? 0)
  }, [])

  const handleClearSelection = useCallback(() => {
    setSelectionCount(viewerRef.current?.clearSelection() ?? 0)
  }, [])

  // Undo/redo: the local stack answers instantly (camera preserved); the
  // backend History records the same sequence and stays authoritative.
  const handleUndo = useCallback(() => {
    const localOk = viewerRef.current?.undo() ?? false
    const sceneId = sceneIdRef.current
    if (!sceneId) return
    void historyOp(sceneId, 'undo').then(async (res) => {
      if (!localOk && res.ok) await reloadAuthoritative(sceneId) // backend-only history (e.g. agent edits after reload)
    }).catch((err) => console.warn('[backend] undo failed:', err))
  }, [reloadAuthoritative])

  const handleRedo = useCallback(() => {
    const sceneId = sceneIdRef.current
    if (!sceneId) return
    void historyOp(sceneId, 'redo').then(async (res) => {
      if (res.ok) await reloadAuthoritative(sceneId)
    }).catch((err) => console.warn('[backend] redo failed:', err))
  }, [reloadAuthoritative])

  const handleResetView = useCallback(() => {
    viewerRef.current?.setView('front', true)
  }, [])

  const handleNavModeToggle = useCallback(() => {
    const v = viewerRef.current
    if (!v) return
    v.setNavigationMode(v.getNavigationMode() === 'fly' ? 'orbit' : 'fly')
  }, [])

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

  // A load failed: re-show the picker and tell the user (the SceneManager
  // loaders reject on a corrupt/undecodable file with no UI feedback of their own).
  const reportLoadError = useCallback((what: string, err: unknown) => {
    const msg = `Couldn't load ${what}: ${err instanceof Error ? err.message : String(err)}`
    console.warn('[load]', msg)
    setHasScene(false)
    setNarration(msg)
  }, [])

  // Render a File locally AND register it with the backend so the agent works.
  const loadFile = useCallback((file: File) => {
    setHasScene(true)
    void (async () => {
      try {
        await viewerRef.current?.loadSplatFile(file)
      } catch (err) {
        reportLoadError(file.name, err)
        return
      }
      // Snapshot the baseline synchronously from the handle (not React state,
      // which hasn't flushed yet) so the export badge measures from THIS load.
      setBaselineCount(viewerRef.current?.getSplatCount() ?? 0)
      void registerScene(file)
    })()
  }, [registerScene, reportLoadError])

  // Render a splat by URL, view-only (no backend scene).
  const loadUrl = useCallback((url: string, label: string) => {
    setHasScene(true)
    disposeAgent()
    sceneIdRef.current = null
    setBackendSceneId(null)
    clearPersistedScene() // view-only: not restorable across refresh
    void (async () => {
      try {
        await viewerRef.current?.loadSplat(url)
        setBaselineCount(viewerRef.current?.getSplatCount() ?? 0)
      } catch (err) {
        reportLoadError(label, err)
      }
    })()
  }, [disposeAgent, reportLoadError])

  const handleFileSelected = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) loadFile(file)
    e.target.value = ''
  }, [loadFile])

  const handleLoadDemo = useCallback(async (demo: DemoSplat) => {
    if (!isBackendLoadable(demo.file)) {
      loadUrl(demo.url, demo.name)
      return
    }
    setHasScene(true)
    try {
      const res = await fetch(demo.url)
      if (!res.ok) throw new Error(`fetch ${demo.url} → ${res.status}`)
      const blob = await res.blob()
      loadFile(new File([blob], demo.file))
    } catch (err) {
      reportLoadError(demo.name, err)
    }
  }, [loadFile, loadUrl, reportLoadError])

  // ── Agent trace → chat/narration state ──
  const processTrace = useCallback((entries: TraceEntry[]) => {
    for (let i = processedTraceRef.current; i < entries.length; i++) {
      const e = entries[i]
      if (e.kind === 'tool_call') {
        const name = String(e.detail?.name ?? e.text ?? 'tool')
        runActionsRef.current.push({
          type: classifyAction(name),
          label: name,
          detail: e.detail?.args ? JSON.stringify(e.detail.args) : undefined,
        })
        setAgentStep(runActionsRef.current.length)
        if (e.text) setNarration(e.text)
      } else if ((e.kind === 'thought' || e.kind === 'narrate') && e.text) {
        setNarration(e.text)
      } else if (e.kind === 'complete') {
        setAgentPaused(false)
        const content = completeContent(e.detail)
        const hadError = Boolean(e.detail?.error)
        const actions = [...runActionsRef.current]
        setMessages((prev) => [...prev, {
          id: `msg-${Date.now()}-assistant`,
          role: 'assistant',
          content,
          timestamp: Date.now(),
          actions: actions.length > 0 ? actions : undefined,
        }])
        setNarration(content)
        setAgentStep(0)
        runActionsRef.current = []
        // The agent edited the backend model; reload the served .ply and
        // adopt the backend's alive-ID list so both sides keep one ID space.
        if (!hadError && sceneIdRef.current) {
          void reloadAuthoritative(sceneIdRef.current)
        }
      }
    }
    processedTraceRef.current = entries.length
  }, [reloadAuthoritative])

  // Build the WS transport + agent for the current scene (once), wiring the
  // PanelBus signals into React state. WS must be OPEN before /agent/run, or
  // early trace events are dropped by the backend.
  const ensureAgent = useCallback(async () => {
    if (agentRef.current) return
    const viewer = viewerRef.current
    const sceneId = sceneIdRef.current
    if (!viewer || !sceneId) throw new Error('no scene')

    const panels = new PanelBus()
    const transport = new WebSocketTransport(sceneWsUrl(sceneId))
    await transport.whenOpen()
    const agent = createAgent({ bridge: makeRendererBridge(viewer), transport, panels })

    processedTraceRef.current = panels.trace.get().length
    unsubsRef.current.push(
      panels.running.subscribe(setIsThinking),
      panels.trace.subscribe(processTrace),
      panels.proposal.subscribe(handleProposalSignal),
    )
    panelsRef.current = panels
    transportRef.current = transport
    agentRef.current = agent
  }, [processTrace, handleProposalSignal])

  const handleSend = useCallback((text: string) => {
    setMessages((prev) => [...prev, {
      id: `msg-${Date.now()}-user`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }])
    setNarration(text)
    setAgentStep(0)

    if (!sceneIdRef.current) {
      const content = registeringSceneRef.current
        ? "Still uploading this scene to the backend — large scenes can take up to a minute. Try again in a moment."
        : hasSceneRef.current
          ? "This scene is view-only — it's a .splat the renderer can show but the backend can't edit. The agent works on .ply scenes; load a .ply from Samples or drag one in."
          : 'Load a .ply scene first — the agent inspects and cleans .ply splats.'
      setMessages((prev) => [...prev, {
        id: `msg-${Date.now()}-assistant`,
        role: 'assistant',
        content,
        timestamp: Date.now(),
      }])
      return
    }

    const sceneId = sceneIdRef.current
    runActionsRef.current = []
    setIsThinking(true)
    // Snapshot the operator's current view as the run's "home" — the agent can
    // return here (reframe) if it gets lost. Captured now, before it moves.
    viewerRef.current?.setHomePose(viewerRef.current.getCameraPose())
    ensureAgent()
      .then(() => runAgent(sceneId, text, stageRef.current))
      .catch((err) => {
        const errMsg = `Error: ${err instanceof Error ? err.message : String(err)}. Is the backend running on :8000?`
        setMessages((prev) => [...prev, {
          id: `msg-${Date.now()}-error`,
          role: 'assistant',
          content: errMsg,
          timestamp: Date.now(),
        }])
        setIsThinking(false)
        setNarration(errMsg)
        setAgentStep(0)
      })
  }, [ensureAgent])

  // Understand is look-only (R15): leaving Clean drops any active tool/selection.
  const handleStageChange = useCallback((next: Stage) => {
    if (isThinking) return // switcher is disabled during a run (AE2 guard)
    if (next === 'understand') {
      setActiveTool(null)
      setEraseMode(false)
      viewerRef.current?.clearSelection()
      setSelectionCount(0)
    }
    stageRef.current = next
    setStage(next)
  }, [isThinking])

  const editingEnabled = stage === 'clean'

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
      />

      {/* Body: viewport + right panel */}
      <div className="flex-1 flex min-h-0">
        {/* Center: Viewport + Narration */}
        <div className="flex-1 min-w-0 flex flex-col bg-bg-deep">
          <div className="flex-1 relative overflow-hidden">
            <ViewerErrorBoundary>
              <ViewerCanvas
                ref={viewerRef}
                onStateChange={handleStateChange}
                onMovementChange={handleMovementChange}
                onRotationChange={handleRotationChange}
                onSelectionChange={handleSelectionChange}
                onManualInput={handleManualInput}
              />
            </ViewerErrorBoundary>

            {/* Selection interaction layer (Clean stage only) */}
            {hasScene && editingEnabled && (
              <SelectionOverlay
                viewerRef={viewerRef}
                tool={activeTool}
                onSelectionChange={handleSelectionChange}
                onManualInput={handleManualInput}
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
              />
            )}

            {/* Rotate + WASD movement pads — every input source lights them
                (R8/R13); a shared flex container declares their layout. */}
            {hasScene && (
              <div className="absolute bottom-3 right-3 z-20 flex items-end gap-2">
                <RotatePad
                  activeRotations={activeRotations}
                  onInput={(dir, active) => {
                    if (active) handleManualInput()
                    viewerRef.current?.setRotationInput(dir, active)
                  }}
                />
                <MovePad
                  activeDirections={activeDirections}
                  onInput={(dir, active) => {
                    if (active) handleManualInput()
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
                  onClick={handleStopAgent}
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
                  onClick={handleResumeAgent}
                  className="rounded border border-white/25 bg-white/10 px-2 py-0.5 font-mono text-[11px] text-white hover:bg-white/20 cursor-pointer"
                >
                  Resume
                </button>
                <button
                  type="button"
                  onClick={handleStopAgent}
                  className="rounded border border-red-400/30 bg-red-500/10 px-2 py-0.5 font-mono text-[11px] text-red-200 hover:bg-red-500/20 cursor-pointer"
                >
                  Stop run
                </button>
              </div>
            )}

            {/* Transient status (edit rejected, etc.) */}
            {!agentPaused && !proposal && status && (
              <div className="absolute top-3 left-1/2 z-30 -translate-x-1/2 rounded border border-white/20 bg-black/70 px-3 py-1.5 font-mono text-xs text-white/90">
                {status}
              </div>
            )}

            {/* Empty state: shown until a scene is loaded */}
            {!hasScene && (
              <EmptyState
                onImport={handleImport}
                onDropFile={loadFile}
              />
            )}
          </div>
          <NarrationBar
            state={viewerState}
            isRunning={isThinking}
            narration={narration}
            step={agentStep}
            maxSteps={15}
          />
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
            skills={skills}
            messages={messages}
            isThinking={isThinking}
            proposal={proposal}
            onProposalDecide={handleProposalDecide}
            onSend={handleSend}
            onClose={() => setRightOpen(false)}
          />
        )}
      </div>
    </div>
  )
}
