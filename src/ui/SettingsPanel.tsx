import { useEffect, useState } from 'react'
import { X, ExternalLink, CheckCircle2, XCircle, Loader2, ChevronRight } from 'lucide-react'
import {
  getProviders,
  saveModelConfig,
  testModelConfig,
  type ModelConfig,
  type ProviderInfo,
} from '../backend/client'
import Button from './Button'

interface SettingsPanelProps {
  isOpen: boolean
  /** The last-known saved config, so the panel opens on the right card. */
  config: ModelConfig | null
  onClose: () => void
  /** Fired after a successful Save so App can refresh its copy + clear the nudge. */
  onSaved: (config: ModelConfig) => void
}

type TestState = { status: 'idle' | 'testing' | 'ok' | 'error'; message?: string }

/**
 * The "choose your AI model" surface (in-app model picker). No code editing,
 * no env files — pick a provider, optionally paste a key, test it, save it.
 * Mirrors ChatPanel's slide-in frame (same 380px right-hand slot).
 */
export default function SettingsPanel({ isOpen, config, onClose, onSaved }: SettingsPanelProps) {
  // The parent only mounts this component while `isOpen` is true (it fully
  // unmounts SettingsPanel on close), so every mount is a fresh "just opened"
  // — form state can seed straight from props via lazy initializers instead
  // of an effect that re-syncs local state from a prop.
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [presetId, setPresetId] = useState<string>(() => config?.preset ?? 'gemini')
  const [model, setModel] = useState(() => config?.model ?? '')
  const [apiKey, setApiKey] = useState('') // never prefilled — the backend can't return it anyway
  const [baseUrl, setBaseUrl] = useState(() => config?.base_url ?? '')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [testState, setTestState] = useState<TestState>({ status: 'idle' })
  const [saving, setSaving] = useState(false)

  // Load the registry once, on mount.
  useEffect(() => {
    getProviders().then(setProviders)
  }, [])

  if (!isOpen) return null

  const selected = providers.find((p) => p.id === presetId)
  const usingEnvKey = config?.preset === presetId && config?.key_source === 'env' && !apiKey

  function selectPreset(p: ProviderInfo) {
    setPresetId(p.id)
    setModel(p.default_model)
    setBaseUrl(p.default_base_url ?? '')
    setApiKey('')
    setTestState({ status: 'idle' })
  }

  async function handleTest() {
    setTestState({ status: 'testing' })
    const result = await testModelConfig({
      preset: presetId,
      model: model || undefined,
      api_key: apiKey || undefined,
      base_url: baseUrl || undefined,
    })
    setTestState(
      result.ok
        ? { status: 'ok', message: `${result.model ?? 'Model'} responded.` }
        : { status: 'error', message: result.error ?? 'Something went wrong.' },
    )
  }

  async function handleSave() {
    setSaving(true)
    try {
      const saved = await saveModelConfig({
        preset: presetId,
        model: model || null,
        api_key: apiKey === '' ? undefined : apiKey,
        base_url: baseUrl || null,
      })
      onSaved(saved)
      onClose()
    } catch (err) {
      setTestState({ status: 'error', message: err instanceof Error ? err.message : 'Save failed.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="h-full w-[380px] flex-none panel flex flex-col animate-slide-in-right"
      style={{ borderRadius: '0' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-subtle shrink-0">
        <h2 className="text-sm font-semibold text-text-primary">AI Model</h2>
        <Button variant="icon" size="sm" onClick={onClose} aria-label="Close settings panel">
          <X size={16} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
        <p className="text-[11px] text-text-dim leading-relaxed">
          Pick what powers the agent. Paid providers need your own API key (usage-based
          billing on your account); the local option is free but needs a model running on
          your machine.
        </p>

        {/* Provider cards */}
        <div className="flex flex-col gap-2">
          {providers.map((p) => {
            const isSelected = p.id === presetId
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => selectPreset(p)}
                className={[
                  'text-left px-3 py-2.5 rounded-lg border transition-colors cursor-pointer',
                  isSelected
                    ? 'border-accent-cyan/60 bg-accent-cyan-dim'
                    : 'border-border-subtle bg-bg-elevated hover:border-border-active',
                ].join(' ')}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[13px] font-medium text-text-primary">{p.label}</span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {p.id === 'gemini' && (
                      <span className="text-[9.5px] uppercase tracking-wide text-accent-cyan">
                        Recommended
                      </span>
                    )}
                    {p.key_in_env && (
                      <span className="text-[9.5px] rounded-full bg-bg-hover px-1.5 py-0.5 text-text-dim">
                        key in env
                      </span>
                    )}
                  </div>
                </div>
                <p className="mt-1 text-[11px] text-text-dim leading-snug">{p.blurb}</p>
              </button>
            )
          })}
        </div>

        {selected && (
          <div className="flex flex-col gap-2.5 pt-1">
            {selected.needs_key && (
              <div className="flex flex-col gap-1">
                <label className="text-[11px] text-text-secondary">API key</label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={usingEnvKey ? 'Using key from environment' : 'Paste your API key'}
                  className="bg-bg-elevated border border-border-subtle rounded-md px-2.5 py-1.5 text-[12px] text-text-primary placeholder:text-text-dim outline-none focus:border-accent-cyan"
                />
                {selected.key_help_url && (
                  <a
                    href={selected.key_help_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-[10.5px] text-accent-cyan hover:underline w-fit"
                  >
                    Get one free <ExternalLink size={9} />
                  </a>
                )}
              </div>
            )}

            {selected.supports_base_url && (
              <div className="flex flex-col gap-1">
                <label className="text-[11px] text-text-secondary">Endpoint URL</label>
                <input
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder={selected.default_base_url}
                  className="bg-bg-elevated border border-border-subtle rounded-md px-2.5 py-1.5 text-[12px] text-text-primary placeholder:text-text-dim outline-none focus:border-accent-cyan font-mono"
                />
                <p className="text-[10.5px] text-text-dim">
                  Ollama default shown. LM Studio usually serves at{' '}
                  <span className="font-mono">http://localhost:1234/v1</span>. Must be a
                  vision-capable model — the agent sees the scene through captured frames.
                </p>
              </div>
            )}

            <div className="flex flex-col gap-1">
              <button
                type="button"
                onClick={() => setAdvancedOpen((p) => !p)}
                className="flex items-center gap-1 text-[11px] text-text-dim hover:text-text-secondary w-fit cursor-pointer"
              >
                <ChevronRight
                  size={11}
                  className={advancedOpen ? 'rotate-90 transition-transform' : 'transition-transform'}
                />
                Advanced
              </button>
              {advancedOpen && (
                <div className="flex flex-col gap-1 pl-3">
                  <label className="text-[11px] text-text-secondary">Model</label>
                  <input
                    type="text"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder={selected.default_model}
                    className="bg-bg-elevated border border-border-subtle rounded-md px-2.5 py-1.5 text-[12px] text-text-primary placeholder:text-text-dim outline-none focus:border-accent-cyan font-mono"
                  />
                </div>
              )}
            </div>

            {testState.status !== 'idle' && (
              <div
                className={[
                  'flex items-start gap-1.5 text-[11px] rounded-md px-2.5 py-2',
                  testState.status === 'ok'
                    ? 'bg-emerald-500/10 text-emerald-300'
                    : testState.status === 'error'
                      ? 'bg-red-500/10 text-red-300'
                      : 'bg-bg-elevated text-text-dim',
                ].join(' ')}
              >
                {testState.status === 'testing' && <Loader2 size={13} className="animate-spin shrink-0 mt-px" />}
                {testState.status === 'ok' && <CheckCircle2 size={13} className="shrink-0 mt-px" />}
                {testState.status === 'error' && <XCircle size={13} className="shrink-0 mt-px" />}
                <span className="leading-snug">
                  {testState.status === 'testing' ? 'Testing…' : testState.message}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="shrink-0 px-4 py-3 border-t border-border-subtle flex items-center gap-2">
        <Button variant="secondary" size="md" onClick={handleTest} disabled={testState.status === 'testing'}>
          Test connection
        </Button>
        <Button variant="primary" size="md" onClick={handleSave} loading={saving} className="flex-1">
          Save
        </Button>
      </div>
    </div>
  )
}
