/**
 * One scene+agent session, shared by both pages (editor and analyst).
 *
 * Scene and agent are ONE hook rather than two on purpose: they are mutually
 * dependent. Registering a scene must dispose the stale agent, and the agent's
 * send path re-registers a scene to recover from a restarted backend. Split
 * into two hooks, each would need the other at construction time.
 *
 * The editor keeps its own editing state (tools, selection, crop box, history,
 * settings); none of that belongs here, and the analyst never has it.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import type { MoveDirection, RotateDirection, ViewerState, ViewerHandle } from '../types/viewer'
import type { ChatMessage, AgentAction } from '../types/agent'
import { createAgent, WebSocketTransport, PanelBus } from '@agent'
import type { Agent, TraceEntry, ProposalState } from '@agent'
import {
  uploadScene, runAgent, sceneWsUrl, scenePlyUrl, isBackendLoadable,
  getAliveIds, getAgentHistory, type SceneVersion,
} from '../backend/client'
import { makeRendererBridge } from '../backend/bridge'
import { classifyAction, completeContent, sceneChanged } from '../backend/trace'
import {
  savePersistedScene, loadPersistedScene, clearPersistedScene, updatePersistedCamera,
} from '../persistence'

const DEFAULT_VIEWER_STATE: ViewerState = {
  splatCount: 0,
  fps: 0,
  cameraPosition: [0, 0, 0],
  fileName: null,
  isLoading: false,
  undoCount: 0,
  navigationMode: 'orbit',
}

/** Does the backend still hold this scene? Scenes are in-memory only, so a
 *  restarted backend loses them while a browser tab still holds the id. */
export async function probeBackendScene(
  sceneId: string,
): Promise<{ present: boolean; ids: Uint32Array | null }> {
  try {
    const ids = await getAliveIds(sceneId)
    return { present: true, ids }
  } catch {
    return { present: false, ids: null }
  }
}

export interface SessionOptions {
  /** Which tool surface the agent runs with. */
  stage: 'clean' | 'understand'
  /** Clean-stage only — the analyst never parks a proposal. */
  onProposal?: (p: ProposalState | null) => void
  /** Restore the last scene from sessionStorage on mount. The analyst loads
   *  by scene id from its URL instead, so it opts out. */
  restoreOnMount?: boolean
}

export interface Session {
  viewerRef: React.RefObject<ViewerHandle | null>
  viewerState: ViewerState
  onViewerStateChange: (s: ViewerState) => void
  activeDirections: ReadonlySet<MoveDirection>
  activeRotations: ReadonlySet<RotateDirection>
  onMovementChange: (dirs: MoveDirection[]) => void
  onRotationChange: (dirs: RotateDirection[]) => void

  hasScene: boolean
  backendSceneId: string | null
  baselineCount: number
  sceneIdRef: React.RefObject<string | null>
  loadFile: (file: File) => void
  loadUrl: (url: string, label: string) => void
  loadBackendScene: (sceneId: string) => Promise<void>
  reloadAuthoritative: (sceneId: string) => Promise<void>

  status: string | null
  showStatus: (text: string) => void
  narration: string
  setNarration: (t: string) => void

  messages: ChatMessage[]
  isThinking: boolean
  agentPaused: boolean
  send: (text: string) => void
  stop: () => void
  resume: () => void
  onManualInput: () => void
  decideProposal: (verdict: 'approved' | 'rejected' | 'adjusted', feedback?: string) => void
  /** Mark the scene as carrying edits the backend never saw, so a transparent
   *  re-upload of the original file can't silently desync it. */
  markLocalOnlyEdit: () => void

  /** True while the viewport shows the untouched upload instead of your edits.
   *  A viewing lens only — the edited scene on the backend is untouched. */
  viewingOriginal: boolean
  /** Switch the viewport between the original upload and the edited scene. */
  showVersion: (version: SceneVersion) => Promise<void>
}

export function useSession(opts: SessionOptions): Session {
  const { stage, onProposal, restoreOnMount = true } = opts

  const viewerRef = useRef<ViewerHandle>(null)
  const [viewerState, setViewerState] = useState<ViewerState>(DEFAULT_VIEWER_STATE)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isThinking, setIsThinking] = useState(false)
  const [narration, setNarration] = useState('')
  // Start "has scene" true when a persisted record exists so the restore effect
  // shows the viewport (not the empty state) without a synchronous setState.
  const [hasScene, setHasScene] = useState(
    () => restoreOnMount && loadPersistedScene() !== null,
  )
  const [activeDirections, setActiveDirections] = useState<ReadonlySet<MoveDirection>>(new Set())
  const [activeRotations, setActiveRotations] = useState<ReadonlySet<RotateDirection>>(new Set())
  const [status, setStatus] = useState<string | null>(null)
  const statusTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [backendSceneId, setBackendSceneId] = useState<string | null>(null)
  const [baselineCount, setBaselineCount] = useState(0)
  const [viewingOriginal, setViewingOriginal] = useState(false)
  // Mirrors viewingOriginal for stale-closure-free reads inside send().
  const viewingOriginalRef = useRef(false)

  /** Transient status toast (e.g. "Edit rejected — scene restored"). */
  const showStatus = useCallback((text: string) => {
    setStatus(text)
    if (statusTimer.current) clearTimeout(statusTimer.current)
    statusTimer.current = setTimeout(() => setStatus(null), 4000)
  }, [])

  const agentRef = useRef<Agent | null>(null)
  const transportRef = useRef<WebSocketTransport | null>(null)
  const panelsRef = useRef<PanelBus | null>(null)
  const sceneIdRef = useRef<string | null>(null)
  const hasSceneRef = useRef(false)
  // Monotonic scene-load generation: every load path (mount restore, file,
  // demo, URL) claims a new generation; a continuation that no longer owns the
  // latest generation must not mutate viewer or scene state.
  const loadGenRef = useRef(0)
  // Large real-world scenes can take up to ~60s to upload+parse on the backend.
  // Without this, a prompt typed during that window sees sceneId===null and
  // wrongly reports "view-only".
  const registeringSceneRef = useRef(false)
  /** The last backend-loadable file — retried when its upload failed. */
  const lastPlyFileRef = useRef<File | null>(null)
  /** Local edits made while unregistered — a retried upload would desync them. */
  const localOnlyEditsRef = useRef(false)
  const stageRef = useRef(stage)
  const unsubsRef = useRef<Array<() => void>>([])
  const processedTraceRef = useRef(0)
  const runActionsRef = useRef<AgentAction[]>([])
  const proposalPendingRef = useRef(false)
  const onProposalRef = useRef(onProposal)

  useEffect(() => { stageRef.current = stage }, [stage])
  useEffect(() => { onProposalRef.current = onProposal }, [onProposal])

  const handleProposalSignal = useCallback((p: ProposalState | null) => {
    proposalPendingRef.current = p !== null
    onProposalRef.current?.(p)
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
    onProposalRef.current?.(null)
  }, [])

  useEffect(() => disposeAgent, [disposeAgent])
  useEffect(() => { hasSceneRef.current = hasScene }, [hasScene])

  // ── Refresh persistence ──
  // On mount, restore the last backend scene if it still exists. Probe /ids
  // first (cheap JSON, 404s when the backend has lost the scene) so a stale
  // record falls back to the empty state instead of a hung load.
  //
  // Load-generation guard: every load path — this restore AND every
  // user-initiated load — claims a monotonic generation. After each await the
  // restore proceeds only while it still owns the latest generation, so
  // choosing a new scene mid-restore can never be clobbered by the stale
  // continuation (success OR failure path).
  useEffect(() => {
    if (!restoreOnMount) return
    const rec = loadPersistedScene()
    if (!rec) return
    const gen = ++loadGenRef.current
    const owns = () => loadGenRef.current === gen
    void (async () => {
      try {
        const ids = await getAliveIds(rec.sceneId)
        if (!owns()) return
        await viewerRef.current?.loadSplat(scenePlyUrl(rec.sceneId))
        if (!owns()) return
        viewerRef.current?.setIdMapFromIds(ids)
        sceneIdRef.current = rec.sceneId
        setBackendSceneId(rec.sceneId)
        setBaselineCount(rec.baseline)
        if (rec.camera) {
          viewerRef.current?.setCameraPose(
            new THREE.Vector3(...rec.camera.position),
            new THREE.Vector3(...rec.camera.target),
            false, // no tween: land exactly where the user left off
          )
        }
        // Put the chat back. The BACKEND keeps the conversation with the scene
        // (scene.chat_history), so the agent still remembers across a reload —
        // only the visible bubbles were lost. Best-effort: a scene that
        // restored fine must not be thrown away because chat didn't.
        try {
          const past = await getAgentHistory(rec.sceneId)
          if (owns() && past.length) {
            setMessages(past
              .filter((m) => m.role === 'user' || m.role === 'assistant')
              .map((m, i) => ({
                id: `restored-${i}`,
                role: m.role === 'user' ? 'user' as const : 'assistant' as const,
                content: m.content,
                timestamp: 0, // unknown: the backend keeps no timestamps
              })))
          }
        } catch (err) {
          console.warn('[persistence] chat history restore failed (scene is fine):', err)
        }
      } catch (err) {
        // The usual cause is a RESTARTED BACKEND: scenes are in-memory only, so
        // the id 404s while the browser still holds it. Say so — silently
        // dropping to the empty page reads as "the app forgot everything".
        console.warn('[persistence] scene restore failed; starting fresh:', err)
        clearPersistedScene()
        if (owns()) {
          setHasScene(false)
          setBackendSceneId(null)
          sceneIdRef.current = null
          showStatus(
            rec.fileName
              ? `The backend no longer has "${rec.fileName}" (it restarts with an empty store) — load it again to continue.`
              : 'The backend no longer has that scene — load it again to continue.',
          )
        }
      }
    })()
    return () => { ++loadGenRef.current } // unmount invalidates too
  }, [restoreOnMount, showStatus])

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

  const onViewerStateChange = useCallback((s: ViewerState) => setViewerState(s), [])
  const onMovementChange = useCallback((dirs: MoveDirection[]) => {
    setActiveDirections(new Set(dirs))
  }, [])
  const onRotationChange = useCallback((dirs: RotateDirection[]) => {
    setActiveRotations(new Set(dirs))
  }, [])

  const [agentPaused, setAgentPaused] = useState(false)
  const isThinkingRef = useRef(false)
  const agentPausedRef = useRef(false)
  useEffect(() => { isThinkingRef.current = isThinking }, [isThinking])
  useEffect(() => { agentPausedRef.current = agentPaused }, [agentPaused])

  const sendPauseSignal = useCallback((type: 'agent_pause' | 'agent_resume') => {
    transportRef.current?.send({ type, id: `${type}-${Date.now()}`, payload: {} })
  }, [])

  /** Manual input during an agent run pauses it at the next tool-call boundary.
   *  The banner persists until Resume or Stop. Exception: while a proposal is
   *  parked, camera inspection is expected review behavior, so it must NOT
   *  pause the (already-blocked) run. */
  const onManualInput = useCallback(() => {
    if (isThinkingRef.current && !agentPausedRef.current && !proposalPendingRef.current) {
      sendPauseSignal('agent_pause')
      setAgentPaused(true)
    }
  }, [sendPauseSignal])

  const resume = useCallback(() => {
    sendPauseSignal('agent_resume')
    setAgentPaused(false)
  }, [sendPauseSignal])

  const stop = useCallback(() => {
    // Resolve any parked proposal first so the blocked loop unwinds before the
    // interrupt (the resolver latch makes this safe even if already resolved).
    panelsRef.current?.proposal.get()?.resolve('rejected', 'operator stopped the run')
    transportRef.current?.send({ type: 'user_interrupt', id: `int-${Date.now()}`, payload: {} })
    // release the paused loop so it can observe the abort
    sendPauseSignal('agent_resume')
    setAgentPaused(false)
  }, [sendPauseSignal])

  /** Operator decision on the parked proposal — resolves via the signal's
   *  latched resolver, which sends the reply and clears the signal. */
  const decideProposal = useCallback(
    (verdict: 'approved' | 'rejected' | 'adjusted', feedback?: string) => {
      panelsRef.current?.proposal.get()?.resolve(verdict, feedback)
    },
    [],
  )

  /**
   * Reload the backend's authoritative scene and adopt its alive-ID list so
   * the viewer's stable ID map keeps matching the backend's ID space.
   */
  const reloadAuthoritative = useCallback(async (sceneId: string) => {
    await viewerRef.current?.loadSplat(scenePlyUrl(sceneId), { keepCamera: true })
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
      lastPlyFileRef.current = null
      clearPersistedScene() // view-only scene: nothing restorable
      return
    }
    // Kept for transparent retry: if this upload fails (backend restarting is
    // the common case), the next chat send re-attempts it instead of wrongly
    // telling the operator their .ply is a view-only .splat.
    lastPlyFileRef.current = file
    localOnlyEditsRef.current = false
    registeringSceneRef.current = true
    setStatus('Uploading scene to backend…')
    try {
      const { id } = await uploadScene(file)
      sceneIdRef.current = id
      setBackendSceneId(id)
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
    ++loadGenRef.current // invalidate any pending restore/load continuation
    setViewingOriginal(false) // a new scene is never "the original of" the old one
    viewingOriginalRef.current = false
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
    ++loadGenRef.current
    setViewingOriginal(false)
    viewingOriginalRef.current = false
    setHasScene(true)
    disposeAgent()
    sceneIdRef.current = null
    lastPlyFileRef.current = null // a stale .ply must never be retried over this scene
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

  /** Load an already-registered backend scene by id — the analyst's entry
   *  point. Adopts the backend's ID space so the two agree after any prior
   *  edit. Throws if the scene is gone so the caller can render its
   *  missing-scene state. */
  const loadBackendScene = useCallback(async (sceneId: string) => {
    const gen = ++loadGenRef.current
    const owns = () => loadGenRef.current === gen
    disposeAgent()
    const probe = await probeBackendScene(sceneId)
    if (!owns()) return
    if (!probe.present) {
      sceneIdRef.current = null
      setBackendSceneId(null)
      setHasScene(false)
      throw new Error(`scene ${sceneId} is no longer loaded`)
    }
    setHasScene(true)
    await viewerRef.current?.loadSplat(scenePlyUrl(sceneId))
    if (!owns()) return
    if (probe.ids) viewerRef.current?.setIdMapFromIds(probe.ids)
    sceneIdRef.current = sceneId
    setBackendSceneId(sceneId)
    setBaselineCount(viewerRef.current?.getSplatCount() ?? 0)
  }, [disposeAgent])

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
        if (e.text) setNarration(e.text)
      } else if ((e.kind === 'thought' || e.kind === 'narrate') && e.text) {
        setNarration(e.text)
      } else if (e.kind === 'complete') {
        setAgentPaused(false)
        const content = completeContent(e.detail)
        const actions = [...runActionsRef.current]
        setMessages((prev) => [...prev, {
          id: `msg-${Date.now()}-assistant`,
          role: 'assistant',
          content,
          timestamp: Date.now(),
          actions: actions.length > 0 ? actions : undefined,
        }])
        setNarration(content)
        runActionsRef.current = []
        // Reload the served .ply whenever the run actually edited the backend
        // model (scene_changed) — a read-only survey must not reload/reframe.
        // An error does NOT suppress this: loop-level failures still report
        // scene_changed: true when edits landed before the failure, and the
        // viewer must resync or it's left showing a stale scene with a
        // desynced ID map.
        if (sceneIdRef.current && sceneChanged(e.detail)) {
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

    // The socket can die out from under a cached agent (backend restart,
    // network drop). Without this, `complete` never arrives, isThinking stays
    // true forever, and send refuses every future run.
    transport.onClose?.(() => {
      disposeAgent()
      setIsThinking(false)
      setAgentPaused(false)
      showStatus('Agent connection lost — the run was stopped. Send again to reconnect.')
    })

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
  }, [processTrace, handleProposalSignal, disposeAgent, showStatus])

  const send = useCallback((text: string) => {
    setMessages((prev) => [...prev, {
      id: `msg-${Date.now()}-user`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }])
    setNarration('') // the live line belongs to the agent's activity, not the ask

    // The agent edits and measures the LIVE scene; running it while the
    // viewport shows the original would act on a scene the operator cannot see.
    if (viewingOriginalRef.current) {
      setMessages((prev) => [...prev, {
        id: `msg-${Date.now()}-assistant`,
        role: 'assistant',
        content: 'You are viewing the original upload. Switch back to Edited before running the agent — it works on your live scene.',
        timestamp: Date.now(),
      }])
      return
    }

    // While a proposal is parked, the run is blocked on the operator's verdict.
    // Typing in chat during review IS adjustment feedback — resolve the parked
    // proposal with it instead of starting a SECOND run. A concurrent run's
    // first proposal would overwrite the parked one and leave the first run's
    // no-timeout future hanging forever.
    if (proposalPendingRef.current) {
      panelsRef.current?.proposal.get()?.resolve('adjusted', text)
      return
    }

    // One run at a time for the WHOLE run lifetime, not just while a proposal
    // is parked: a second run would race edits/undo against the same history,
    // and its first proposal would orphan the blocked one. The backend also
    // 409s this; refusing here keeps the UX clear.
    if (isThinkingRef.current) {
      setMessages((prev) => [...prev, {
        id: `msg-${Date.now()}-assistant`,
        role: 'assistant',
        content: 'A run is already active — Stop it (or wait for it to finish) before sending a new task.',
        timestamp: Date.now(),
      }])
      return
    }

    const startRun = (sceneId: string) => {
      runActionsRef.current = []
      setIsThinking(true)
      // Snapshot the operator's current view as the run's "home" — the agent
      // can return here (reframe) if it gets lost. Captured before it moves.
      viewerRef.current?.setHomePose(viewerRef.current.getCameraPose())
      ensureAgent()
        .then(() => {
          // Re-assert AFTER ensureAgent: the first ensureAgent() subscribes
          // panels.running, whose subscribe REPLAYS the current value (false)
          // — without this the whole first run shows no thinking indicator.
          setIsThinking(true)
          return runAgent(sceneId, text, stageRef.current)
        })
        .catch((err) => {
          const text404 = err instanceof Error ? err.message : String(err)
          // A restarted backend loses its in-memory scenes: the held scene id
          // 404s while the page still shows the splat. Re-register the kept
          // file and rerun instead of surfacing a dead-end error.
          if (/404/.test(text404) && lastPlyFileRef.current && !localOnlyEditsRef.current) {
            const file = lastPlyFileRef.current
            disposeAgent()
            sceneIdRef.current = null
            setNarration('Backend was restarted — re-uploading the scene…')
            void registerScene(file).then(() => {
              if (sceneIdRef.current) {
                startRun(sceneIdRef.current)
              } else {
                setIsThinking(false)
                showStatus('Re-upload failed — is the backend running on :8000?')
              }
            })
            return
          }
          const errMsg = `Error: ${text404}. Is the backend running on :8000?`
          setMessages((prev) => [...prev, {
            id: `msg-${Date.now()}-error`,
            role: 'assistant',
            content: errMsg,
            timestamp: Date.now(),
          }])
          setIsThinking(false)
          setNarration(errMsg)
        })
    }

    if (!sceneIdRef.current) {
      // A .ply whose backend upload failed (backend down/restarting when the
      // scene loaded) is RETRIED here, then the request runs — the operator
      // shouldn't have to diagnose that. Blocked only by local edits made
      // while unregistered (re-uploading the original file would desync them).
      const retryFile = lastPlyFileRef.current
      if (!registeringSceneRef.current && retryFile && !localOnlyEditsRef.current) {
        setIsThinking(true)
        setNarration('Reconnecting the scene to the backend…')
        void registerScene(retryFile).then(() => {
          if (sceneIdRef.current) {
            startRun(sceneIdRef.current)
          } else {
            setIsThinking(false)
            setMessages((prev) => [...prev, {
              id: `msg-${Date.now()}-assistant`,
              role: 'assistant',
              content: "Can't reach the backend on :8000 — is it running? Once it's up, send your message again.",
              timestamp: Date.now(),
            }])
          }
        })
        return
      }
      const content = registeringSceneRef.current
        ? 'Still uploading this scene to the backend — large scenes can take up to a minute. Try again in a moment.'
        : retryFile
          ? 'The backend upload for this .ply failed earlier and you have made local edits since — reload the file to reconnect the agent.'
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

    startRun(sceneIdRef.current)
  }, [ensureAgent, registerScene, disposeAgent, showStatus])

  /** Marks the scene as carrying edits the backend never saw, so a transparent
   *  re-upload of the original file can't silently desync it. */
  const markLocalOnlyEdit = useCallback(() => {
    localOnlyEditsRef.current = true
  }, [])

  /**
   * Show the untouched upload or the edited scene. A VIEWING LENS: nothing on
   * the backend changes, so looking at the original can never cost you edits.
   *
   * Editing is refused while the original is showing — the viewer's stable ID
   * map is indexed against the EDITED alive set, so an edit made against the
   * original's packing would silently desync the frontend from the backend.
   * Switching back re-adopts the backend's ids to restore that alignment.
   */
  const showVersion = useCallback(async (version: SceneVersion) => {
    const sceneId = sceneIdRef.current
    if (!sceneId) return
    if (version === 'original') {
      setViewingOriginal(true)
      viewingOriginalRef.current = true
      await viewerRef.current?.loadSplat(scenePlyUrl(sceneId, 'original'), { keepCamera: true })
      return
    }
    setViewingOriginal(false)
    viewingOriginalRef.current = false
    await reloadAuthoritative(sceneId)
  }, [reloadAuthoritative])

  return {
    viewerRef,
    viewerState,
    onViewerStateChange,
    activeDirections,
    activeRotations,
    onMovementChange,
    onRotationChange,
    hasScene,
    backendSceneId,
    baselineCount,
    sceneIdRef,
    loadFile,
    loadUrl,
    loadBackendScene,
    reloadAuthoritative,
    status,
    showStatus,
    narration,
    setNarration,
    messages,
    isThinking,
    agentPaused,
    send,
    stop,
    resume,
    onManualInput,
    decideProposal,
    markLocalOnlyEdit,
    viewingOriginal,
    showVersion,
  }
}
