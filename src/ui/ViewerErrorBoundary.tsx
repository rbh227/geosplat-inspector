import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Catches render/runtime failures from the 3D viewer (most commonly a WebGL
 * context that won't initialize — headless sandboxes, blocklisted GPUs, lost
 * contexts). Without this, a single canvas error unmounts the whole React tree
 * and the app goes blank. Here it degrades to an on-theme notice instead.
 */
export default class ViewerErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.warn('[viewer] render failed:', error)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="absolute inset-0 flex items-center justify-center p-8">
        <div className="max-w-[420px] flex flex-col items-center text-center gap-4">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
               stroke="var(--color-accent-cyan-muted)" strokeWidth="1.4"
               strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 8l-9-5-9 5v8l9 5 9-5V8z" /><path d="M3 8l9 5 9-5" /><path d="M12 13v9" />
          </svg>
          <h2 className="font-display text-[22px] font-semibold text-text-primary tracking-tight">
            The viewport couldn't start
          </h2>
          <p className="text-[13px] text-text-secondary leading-relaxed">
            The renderer needs a working WebGL context. Try a hardware-accelerated
            browser, or check that your GPU isn't blocklisted.
          </p>
          <button
            onClick={() => this.setState({ error: null })}
            className="btn-phosphor px-5 py-2 rounded-md text-[13px] font-semibold cursor-pointer"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }
}
