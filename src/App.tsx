import { useCallback, useRef, useState } from 'react'
import type { ViewerState, ViewerHandle } from './types/viewer'
import type { ChatMessage, AgentAction } from './types/agent'
import { runAgentLoop } from './agent/loop'
import ViewerCanvas from './viewer/ViewerCanvas'
import TopBar from './ui/TopBar'
import CapabilitiesPanel from './ui/CapabilitiesPanel'
import NarrationBar from './ui/NarrationBar'
import InspectorPanel from './ui/InspectorPanel'
import WelcomePage from './welcome/WelcomePage'

const DEFAULT_VIEWER_STATE: ViewerState = {
  splatCount: 0,
  fps: 0,
  cameraPosition: [0, 0, 0],
  fileName: null,
  isLoading: false,
  undoCount: 0,
}

export default function App() {
  const viewerRef = useRef<ViewerHandle>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [viewerState, setViewerState] = useState<ViewerState>(DEFAULT_VIEWER_STATE)
  const [leftOpen, setLeftOpen] = useState(true)
  const [rightOpen, setRightOpen] = useState(true)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isThinking, setIsThinking] = useState(false)
  const [narration, setNarration] = useState('')
  const [agentStep, setAgentStep] = useState(0)
  const [welcomeVisible, setWelcomeVisible] = useState(true)
  const [welcomeExiting, setWelcomeExiting] = useState(false)

  const handleStateChange = useCallback((state: ViewerState) => {
    setViewerState(state)
  }, [])

  // ── Cleanup actions ──
  const handleCleanOpacity = useCallback((threshold: number) => {
    viewerRef.current?.cleanOpacity(threshold)
  }, [])

  const handleRemoveOutliers = useCallback((k: number) => {
    viewerRef.current?.removeOutliers(k)
  }, [])

  const handleCrop = useCallback(() => {
    const bbox = viewerRef.current?.getBoundingBox()
    if (bbox) viewerRef.current?.cropBbox(bbox.min, bbox.max)
  }, [])

  const handleUndo = useCallback(() => {
    viewerRef.current?.undo()
  }, [])

  const handleResetView = useCallback(() => {
    viewerRef.current?.setView('front', true)
  }, [])

  const handleImport = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileSelected = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) viewerRef.current?.loadSplatFile(file)
    e.target.value = ''
  }, [])

  // ── Welcome page ──
  const handleWelcomeLoadSample = useCallback(() => {
    viewerRef.current?.loadSplat('/bonsai.splat')
    setWelcomeExiting(true)
  }, [])

  const handleWelcomeLoadFile = useCallback((file: File) => {
    viewerRef.current?.loadSplatFile(file)
    setWelcomeExiting(true)
  }, [])

  const handleWelcomeLoadUrl = useCallback((url: string) => {
    viewerRef.current?.loadSplat(url)
    setWelcomeExiting(true)
  }, [])

  const handleWelcomeExitDone = useCallback(() => {
    setWelcomeVisible(false)
    setWelcomeExiting(false)
  }, [])

  // ── Agent send ──
  const handleSend = useCallback((text: string) => {
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}-user`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
    }
    setMessages((prev) => [...prev, userMsg])
    setNarration(text)
    setAgentStep(0)

    const viewer = viewerRef.current
    const apiKey = import.meta.env.VITE_GEMINI_API_KEY

    if (!viewer || !apiKey) {
      setIsThinking(true)
      setTimeout(() => {
        const reply = apiKey
          ? 'No scene loaded. Drag and drop a .ply file first.'
          : 'Agent not connected. Add VITE_GEMINI_API_KEY to your .env file and restart.'
        setMessages((prev) => [...prev, {
          id: `msg-${Date.now()}-assistant`,
          role: 'assistant',
          content: reply,
          timestamp: Date.now(),
        }])
        setIsThinking(false)
        setNarration(reply)
      }, 600)
      return
    }

    const actions: AgentAction[] = []
    let stepNum = 0

    runAgentLoop(
      text,
      [],
      viewer,
      { model: 'gemini-2.5-flash', maxSteps: 15 },
      (action) => {
        actions.push(action)
        stepNum++
        setAgentStep(stepNum)
        setNarration(action.label + (action.detail ? ` — ${action.detail}` : ''))
      },
      setIsThinking,
    )
      .then((answer) => {
        setMessages((prev) => [...prev, {
          id: `msg-${Date.now()}-assistant`,
          role: 'assistant',
          content: answer,
          timestamp: Date.now(),
          actions: actions.length > 0 ? [...actions] : undefined,
        }])
        setNarration(answer)
        setAgentStep(0)
      })
      .catch((err) => {
        const errMsg = `Error: ${err instanceof Error ? err.message : String(err)}`
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
  }, [])

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

      {/* Welcome overlay */}
      {welcomeVisible && (
        <WelcomePage
          isExiting={welcomeExiting}
          onLoadSample={handleWelcomeLoadSample}
          onLoadFile={handleWelcomeLoadFile}
          onLoadUrl={handleWelcomeLoadUrl}
          onExitDone={handleWelcomeExitDone}
        />
      )}

      {/* Main workspace (visible after welcome exits) */}
      {!welcomeVisible && (
        <>
          {/* Top bar */}
          <TopBar
            state={viewerState}
            leftOpen={leftOpen}
            rightOpen={rightOpen}
            onToggleLeft={() => setLeftOpen((p) => !p)}
            onToggleRight={() => setRightOpen((p) => !p)}
            onImport={handleImport}
            onResetView={handleResetView}
          />

          {/* Body: left panel + viewport + right panel */}
          <div className="flex-1 flex min-h-0">
            {/* Left: Capabilities */}
            {leftOpen && (
              <CapabilitiesPanel
                onSendPrompt={handleSend}
                onCleanOpacity={handleCleanOpacity}
                onRemoveOutliers={handleRemoveOutliers}
                onCrop={handleCrop}
                onUndo={handleUndo}
                canUndo={viewerState.undoCount > 0}
                undoCount={viewerState.undoCount}
                onClose={() => setLeftOpen(false)}
              />
            )}

            {/* Left collapsed rail */}
            {!leftOpen && (
              <div className="w-[46px] flex-none bg-bg-surface border-r border-border-subtle flex flex-col items-center pt-2.5 gap-3.5">
                <button
                  onClick={() => setLeftOpen(true)}
                  className="w-[30px] h-[30px] flex items-center justify-center border border-border-active bg-bg-elevated text-text-secondary rounded-[5px] cursor-pointer hover:bg-bg-hover hover:text-text-primary"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M9 6l6 6-6 6"/></svg>
                </button>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#46535F" strokeWidth="1.7" strokeLinejoin="round"><path d="M3 11l19-9-9 19-2-8-8-2z"/></svg>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#46535F" strokeWidth="1.7" strokeLinecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#46535F" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M19 20H8.4L3.7 15.3a1.5 1.5 0 0 1 0-2.1l8.4-8.4a1.5 1.5 0 0 1 2.1 0l5.4 5.4a1.5 1.5 0 0 1 0 2.1L13 20"/></svg>
              </div>
            )}

            {/* Center: Viewport + Narration */}
            <div className="flex-1 min-w-0 flex flex-col bg-bg-deep">
              <div className="flex-1 relative overflow-hidden">
                <ViewerCanvas ref={viewerRef} onStateChange={handleStateChange} />
                {/* Vignette overlay */}
                <div className="absolute inset-0 pointer-events-none" style={{
                  background: 'radial-gradient(circle at 50% 42%, transparent 38%, rgba(0,0,0,0.45) 100%)'
                }} />
              </div>
              <NarrationBar
                isRunning={isThinking}
                narration={narration}
                step={agentStep}
                maxSteps={15}
              />
            </div>

            {/* Right: Inspector Panel */}
            {rightOpen && (
              <InspectorPanel
                messages={messages}
                isThinking={isThinking}
                onSend={handleSend}
                onClose={() => setRightOpen(false)}
              />
            )}

            {/* Right collapsed rail */}
            {!rightOpen && (
              <div className="w-[46px] flex-none bg-bg-surface border-l border-border-subtle flex flex-col items-center pt-2.5">
                <button
                  onClick={() => setRightOpen(true)}
                  className="w-[30px] h-[30px] flex items-center justify-center border border-border-active bg-bg-elevated text-text-secondary rounded-[5px] cursor-pointer hover:bg-bg-hover hover:text-text-primary"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M15 6l-6 6 6 6"/></svg>
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
