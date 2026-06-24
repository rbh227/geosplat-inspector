import { useCallback, useRef, useState } from 'react'
import { Download, Video, ImageIcon, FolderOpen, Globe, ArrowRight, ArrowDown } from 'lucide-react'
import MenuBar from './MenuBar'
import RobotScene from './RobotScene'

interface WelcomePageProps {
  isExiting: boolean
  onLoadSample: () => void
  onLoadFile: (file: File) => void
  onLoadUrl: (url: string) => void
  onExitDone: () => void
}

const SPLAT_ACCEPT = '.ply,.splat,.spz,.ksplat'
const IMAGE_ACCEPT = '.png,.jpg,.jpeg,.webp,.tiff,.bmp'
const VIDEO_ACCEPT = '.mp4,.mov,.webm,.avi,.mkv'

/* ── Card colour system ── */
const ACCENT = {
  cyan:   { bg: 'rgba(52,200,255,.10)', border: 'rgba(52,200,255,.25)', glow: 'rgba(52,200,255,.45)', color: '#34c8ff', gradient: 'from-[#34c8ff]/20 to-[#34c8ff]/5' },
  orange: { bg: 'rgba(249,162,59,.10)', border: 'rgba(249,162,59,.25)', glow: 'rgba(249,162,59,.45)', color: '#f9a23b', gradient: 'from-[#f9a23b]/20 to-[#f9a23b]/5' },
  green:  { bg: 'rgba(74,222,128,.10)',  border: 'rgba(74,222,128,.25)', glow: 'rgba(74,222,128,.45)', color: '#6ee7a8', gradient: 'from-[#6ee7a8]/20 to-[#6ee7a8]/5' },
  violet: { bg: 'rgba(167,139,250,.10)', border: 'rgba(167,139,250,.25)', glow: 'rgba(167,139,250,.45)', color: '#b9a4ff', gradient: 'from-[#b9a4ff]/20 to-[#b9a4ff]/5' },
} as const

const CARDS = [
  { id: 'splat',  Icon: Download,    label: 'Import Splat / PLY', sub: '.splat, .ply, .spz, .ksplat', accent: ACCENT.cyan },
  { id: 'video',  Icon: Video,       label: 'Import Video',       sub: '.mp4, .mov, .webm',          accent: ACCENT.orange },
  { id: 'images', Icon: ImageIcon,   label: 'Import Images',      sub: '.png, .jpg, .webp',          accent: ACCENT.green },
  { id: 'sample', Icon: FolderOpen,  label: 'Load Sample',        sub: 'Bonsai demo scene',          accent: ACCENT.violet },
] as const

export default function WelcomePage({ isExiting, onLoadSample, onLoadFile, onLoadUrl, onExitDone }: WelcomePageProps) {
  const splatInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const activeCardRef = useRef<HTMLElement | null>(null)
  const [statusText, setStatusText] = useState('Ready')
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [url, setUrl] = useState('')

  const openSplatPicker = useCallback(() => splatInputRef.current?.click(), [])
  const openVideoPicker = useCallback(() => videoInputRef.current?.click(), [])
  const openImagePicker = useCallback(() => imageInputRef.current?.click(), [])

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) onLoadFile(file)
    },
    [onLoadFile],
  )

  const handleCardClick = useCallback(
    (id: string) => {
      switch (id) {
        case 'splat': openSplatPicker(); break
        case 'video': openVideoPicker(); break
        case 'images': openImagePicker(); break
        case 'sample': onLoadSample(); break
      }
    },
    [openSplatPicker, openVideoPicker, openImagePicker, onLoadSample],
  )

  const handleUrlSubmit = useCallback(() => {
    const trimmed = url.trim()
    if (trimmed) { onLoadUrl(trimmed); setUrl('') }
  }, [url, onLoadUrl])

  /* ---- Drag-and-drop ---- */
  const [isDragOver, setIsDragOver] = useState(false)
  const handleDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); setIsDragOver(true) }, [])
  const handleDragLeave = useCallback((e: React.DragEvent) => { e.preventDefault(); if (e.currentTarget === e.target) setIsDragOver(false) }, [])
  const handleDrop = useCallback((e: React.DragEvent) => { e.preventDefault(); setIsDragOver(false); const f = e.dataTransfer.files[0]; if (f) onLoadFile(f) }, [onLoadFile])

  return (
    <div
      className={`absolute inset-0 z-50 ${isExiting ? 'animate-welcome-exit' : ''}`}
      style={{ background: '#06080c' }}
      onAnimationEnd={isExiting ? onExitDone : undefined}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Hidden file inputs */}
      <input ref={splatInputRef} type="file" accept={SPLAT_ACCEPT} className="hidden" onChange={handleFileChange} />
      <input ref={videoInputRef} type="file" accept={VIDEO_ACCEPT} className="hidden" onChange={handleFileChange} />
      <input ref={imageInputRef} type="file" accept={IMAGE_ACCEPT} className="hidden" onChange={handleFileChange} multiple />

      {/* Aurora glow behind robot */}
      <div
        className="fixed inset-0 z-0 pointer-events-none"
        style={{
          background: 'radial-gradient(46% 42% at 50% 56%, rgba(249,162,59,.20), transparent 60%), radial-gradient(60% 55% at 50% 55%, rgba(52,200,255,.16), transparent 62%)',
          filter: 'saturate(1.05)',
        }}
      />

      {/* 3D Robot */}
      <RobotScene activeCardRef={activeCardRef} />

      {/* Drag overlay */}
      {isDragOver && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center" style={{ background: 'rgba(6,8,12,.85)' }}>
          <div
            className="text-center p-12 rounded-3xl"
            style={{
              border: '2px dashed #34c8ff',
              background: 'rgba(52,200,255,.04)',
              boxShadow: '0 0 60px rgba(52,200,255,.15), inset 0 0 40px rgba(52,200,255,.05)',
            }}
          >
            <div style={{ marginBottom: 12, color: '#34c8ff' }}><ArrowDown size={40} /></div>
            <p style={{ color: '#34c8ff', fontSize: 20, fontWeight: 700 }}>Drop to import</p>
            <p style={{ color: '#5d6b7a', fontSize: 14, marginTop: 6 }}>.splat, .ply, .spz, images, or video</p>
          </div>
        </div>
      )}

      {/* Menu bar */}
      <MenuBar
        onNewScene={() => {}}
        onOpenFile={openSplatPicker}
        onImportFile={openSplatPicker}
        onImportVideo={openVideoPicker}
        onImportImages={openImagePicker}
        onLoadSample={onLoadSample}
        onUndo={() => {}}
        canUndo={false}
      />

      {/* Title (above robot) */}
      <div className="fixed inset-x-0 top-[80px] z-[4] flex flex-col items-center pointer-events-none">
        <div
          className="flex items-center gap-2.5 mb-3.5"
          style={{ fontSize: 12, letterSpacing: '.34em', fontWeight: 600, color: '#34c8ff', textTransform: 'uppercase' as const }}
        >
          <span className="w-[5px] h-[5px] rounded-full" style={{ background: '#34c8ff', boxShadow: '0 0 8px #34c8ff' }} />
          AI-Powered 3D Scene Viewer
          <span className="w-[5px] h-[5px] rounded-full" style={{ background: '#34c8ff', boxShadow: '0 0 8px #34c8ff' }} />
        </div>
        <h1 style={{ fontSize: 64, fontWeight: 800, letterSpacing: '-.02em', margin: '0 0 18px', color: '#e7edf3' }}>
          GeoSplat
        </h1>
        <p style={{ fontSize: 16, color: '#9fb0c0', margin: 0 }}>
          View, edit &amp; clean Gaussian splats with AI assistance
        </p>
      </div>

      {/* Cards grid (around robot) */}
      <div
        className="fixed inset-0 z-[4] pointer-events-none"
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gridTemplateRows: '1fr 1fr',
          maxWidth: 1180,
          margin: '0 auto',
          padding: '150px 40px 130px',
        }}
      >
        {CARDS.map((card, i) => {
          const isHovered = hoveredId === card.id
          return (
            <div
              key={card.id}
              role="button"
              tabIndex={0}
              className="pointer-events-auto group focus-ring rounded-2xl"
              onMouseEnter={(e) => {
                activeCardRef.current = e.currentTarget
                setHoveredId(card.id)
                setStatusText(`Target locked \u2014 ${card.label}`)
              }}
              onMouseLeave={() => {
                activeCardRef.current = null
                setHoveredId(null)
                setStatusText('Ready')
              }}
              onClick={() => handleCardClick(card.id)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleCardClick(card.id) } }}
              style={{
                gridArea: `${Math.floor(i / 2) + 1} / ${(i % 2) + 1}`,
                alignSelf: i >= 2 ? 'end' : 'start',
                justifySelf: i % 2 === 0 ? 'start' : 'end',
                width: 280,
                cursor: 'pointer',
                position: 'relative',
                /* Staggered entrance */
                opacity: 0,
                animation: `card-orbit-in 700ms cubic-bezier(0.16, 1, 0.3, 1) ${200 + i * 100}ms forwards`,
              }}
            >
              {/* Glow orb behind card (visible on hover) */}
              <div
                className="absolute -inset-4 rounded-3xl pointer-events-none"
                style={{
                  background: `radial-gradient(circle at 50% 50%, ${card.accent.glow}, transparent 70%)`,
                  opacity: isHovered ? 0.35 : 0,
                  transition: 'opacity .4s ease',
                  filter: 'blur(20px)',
                }}
              />

              {/* Card body */}
              <div
                className="relative overflow-hidden rounded-2xl"
                style={{
                  padding: '18px 20px',
                  display: 'flex',
                  gap: 16,
                  alignItems: 'center',
                  background: isHovered
                    ? `linear-gradient(135deg, rgba(18,24,33,.85), rgba(14,18,26,.9))`
                    : 'linear-gradient(180deg, rgba(18,24,33,.72), rgba(10,14,20,.72))',
                  border: `1px solid ${isHovered ? card.accent.border : 'rgba(27,37,49,.8)'}`,
                  backdropFilter: 'blur(16px) saturate(1.2)',
                  WebkitBackdropFilter: 'blur(16px) saturate(1.2)',
                  transition: 'all .35s cubic-bezier(0.16, 1, 0.3, 1)',
                  transform: isHovered ? 'translateY(-4px) scale(1.02)' : 'translateY(0) scale(1)',
                  boxShadow: isHovered
                    ? `0 0 0 1px ${card.accent.border}, 0 8px 32px rgba(0,0,0,.5), 0 0 28px ${card.accent.glow}`
                    : '0 2px 12px rgba(0,0,0,.3)',
                }}
              >
                {/* Shimmer sweep on hover */}
                <div
                  className="absolute inset-0 pointer-events-none"
                  style={{
                    background: `linear-gradient(105deg, transparent 40%, ${card.accent.bg} 50%, transparent 60%)`,
                    transform: isHovered ? 'translateX(200%)' : 'translateX(-200%)',
                    transition: 'transform .8s ease',
                    opacity: 0.6,
                  }}
                />

                {/* Top edge glow line */}
                <div
                  className="absolute top-0 left-4 right-4 h-px pointer-events-none"
                  style={{
                    background: `linear-gradient(90deg, transparent, ${card.accent.color}, transparent)`,
                    opacity: isHovered ? 0.6 : 0,
                    transition: 'opacity .35s ease',
                  }}
                />

                {/* Icon container */}
                <div className="relative flex-shrink-0">
                  {/* Icon ring pulse */}
                  <div
                    className="absolute inset-0 rounded-xl pointer-events-none"
                    style={{
                      border: `1.5px solid ${card.accent.color}`,
                      opacity: isHovered ? 0.4 : 0,
                      transition: 'opacity .35s ease, transform .35s ease',
                      transform: isHovered ? 'scale(1.25)' : 'scale(1)',
                    }}
                  />
                  <div
                    className="relative grid place-items-center"
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: 12,
                      background: card.accent.bg,
                      border: `1px solid ${isHovered ? card.accent.border : 'transparent'}`,
                      color: card.accent.color,
                      transition: 'all .35s ease',
                      transform: isHovered ? 'rotate(6deg) scale(1.08)' : 'rotate(0) scale(1)',
                      boxShadow: isHovered ? `0 0 16px ${card.accent.glow}` : 'none',
                    }}
                  >
                    <card.Icon size={20} />
                  </div>
                </div>

                {/* Text */}
                <div className="relative z-10">
                  <div
                    style={{
                      fontWeight: 650,
                      fontSize: 15,
                      color: isHovered ? '#fff' : '#e7edf3',
                      transition: 'color .2s ease',
                    }}
                  >
                    {card.label}
                  </div>
                  <div
                    style={{
                      color: isHovered ? '#8899aa' : '#5d6b7a',
                      fontSize: 12.5,
                      marginTop: 3,
                      transition: 'color .2s ease',
                    }}
                  >
                    {card.sub}
                  </div>
                </div>

                {/* Arrow indicator on hover */}
                <div
                  className="ml-auto relative z-10"
                  style={{
                    opacity: isHovered ? 1 : 0,
                    transform: isHovered ? 'translateX(0)' : 'translateX(-8px)',
                    transition: 'all .3s ease',
                    color: card.accent.color,
                  }}
                >
                  <ArrowRight size={16} />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* URL input dock */}
      <div className="fixed z-[4] pointer-events-auto" style={{ left: '50%', transform: 'translateX(-50%)', bottom: 64, width: 'min(560px, 76vw)' }}>
        <div className="relative group">
          {/* Input glow */}
          <div
            className="absolute -inset-1 rounded-2xl pointer-events-none"
            style={{
              background: 'linear-gradient(135deg, rgba(52,200,255,.08), rgba(249,162,59,.06))',
              opacity: url.length > 0 ? 1 : 0,
              transition: 'opacity .3s ease',
              filter: 'blur(8px)',
            }}
          />
          <span className="absolute pointer-events-none z-10" style={{ left: 14, top: '50%', transform: 'translateY(-50%)', opacity: .45 }}>
            <Globe size={16} />
          </span>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleUrlSubmit()}
            placeholder="Paste a .splat URL..."
            className="relative"
            style={{
              width: '100%',
              height: 48,
              borderRadius: 14,
              border: '1px solid rgba(27,37,49,.8)',
              background: 'rgba(10,14,20,.75)',
              color: '#e7edf3',
              padding: '0 48px 0 42px',
              fontSize: 14,
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
              outline: 'none',
              transition: 'border-color .2s ease, box-shadow .2s ease',
            }}
            onFocus={(e) => {
              e.target.style.borderColor = 'rgba(52,200,255,.3)'
              e.target.style.boxShadow = '0 0 20px rgba(52,200,255,.08)'
            }}
            onBlur={(e) => {
              e.target.style.borderColor = 'rgba(27,37,49,.8)'
              e.target.style.boxShadow = 'none'
            }}
          />
          {/* Submit arrow */}
          {url.trim().length > 0 && (
            <button
              onClick={handleUrlSubmit}
              className="absolute z-10 grid place-items-center cursor-pointer focus-ring"
              style={{
                right: 8,
                top: '50%',
                transform: 'translateY(-50%)',
                width: 32,
                height: 32,
                borderRadius: 8,
                background: 'rgba(52,200,255,.12)',
                color: '#34c8ff',
                border: '1px solid rgba(52,200,255,.2)',
                transition: 'all .15s ease',
              }}
              aria-label="Submit URL"
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(52,200,255,.2)'
                e.currentTarget.style.borderColor = 'rgba(52,200,255,.4)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(52,200,255,.12)'
                e.currentTarget.style.borderColor = 'rgba(52,200,255,.2)'
              }}
            >
              <ArrowRight size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Hint */}
      <div className="fixed left-0 right-0 z-[4] text-center pointer-events-none" style={{ bottom: 34, color: '#46535f', fontSize: 12.5 }}>
        Drag &amp; drop files anywhere &middot; the robot tracks your cursor &middot; File &rarr; Import
      </div>

      {/* Status bar */}
      <div
        className="fixed left-0 right-0 bottom-0 z-[5] flex items-center justify-between"
        style={{ height: 26, padding: '0 16px', color: '#3c4754', fontSize: 11.5, borderTop: '1px solid rgba(255,255,255,.04)' }}
      >
        <span
          style={{
            transition: 'color .2s ease',
            color: hoveredId ? '#34c8ff' : '#3c4754',
          }}
        >
          {hoveredId && <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#34c8ff', marginRight: 8, boxShadow: '0 0 6px #34c8ff' }} />}
          {statusText}
        </span>
        <span>GeoSplat Inspector v0.1</span>
      </div>
    </div>
  )
}
