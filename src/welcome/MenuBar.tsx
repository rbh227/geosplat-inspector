import { useState, useRef, useEffect, useCallback } from 'react'
import {
  FilePlus,
  FolderOpen,
  Clock,
  Save,
  SaveAll,
  Import,
  FileOutput,
  Upload,
  BoxSelect,
  MousePointerClick,
  Trash2,
  Lock,
  Unlock,
  Copy,
  Scissors,
  Clapperboard,
  Camera,
  Settings,
  SunMedium,
  Info,
  Keyboard,
  BookOpen,
  Image,
  FileVideo,
  ChevronRight,
} from 'lucide-react'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface MenuItem {
  label: string
  icon?: React.ReactNode
  shortcut?: string
  separator?: boolean
  disabled?: boolean
  children?: MenuItem[]
  action?: () => void
}

interface MenuBarProps {
  onNewScene: () => void
  onOpenFile: () => void
  onImportFile: () => void
  onImportVideo: () => void
  onImportImages: () => void
  onLoadSample: () => void
  onUndo: () => void
  canUndo: boolean
}

/* ------------------------------------------------------------------ */
/*  Menu definitions                                                   */
/* ------------------------------------------------------------------ */

function buildMenus(props: MenuBarProps): { label: string; items: MenuItem[] }[] {
  return [
    {
      label: 'File',
      items: [
        { label: 'New', icon: <FilePlus size={15} />, shortcut: '\u2318N', action: props.onNewScene },
        { label: 'Open', icon: <FolderOpen size={15} />, shortcut: '\u2318O', action: props.onOpenFile },
        { label: 'Open Recent', icon: <Clock size={15} />, children: [
          { label: 'No recent files', disabled: true },
        ]},
        { label: '', separator: true },
        { label: 'Save', icon: <Save size={15} />, shortcut: '\u2318S', disabled: true },
        { label: 'Save As...', icon: <SaveAll size={15} />, shortcut: '\u21E7\u2318S', disabled: true },
        { label: '', separator: true },
        { label: 'Import Splat / PLY...', icon: <Import size={15} />, action: props.onImportFile },
        { label: 'Import Video...', icon: <FileVideo size={15} />, action: props.onImportVideo },
        { label: 'Import Images...', icon: <Image size={15} />, action: props.onImportImages },
        { label: '', separator: true },
        { label: 'Export', icon: <FileOutput size={15} />, children: [
          { label: 'Export as .splat', action: () => {} },
          { label: 'Export as .ply', action: () => {} },
          { label: 'Export as .spz', disabled: true },
        ]},
        { label: 'Publish...', icon: <Upload size={15} />, disabled: true },
        { label: '', separator: true },
        { label: 'Load Sample Scene', icon: <FolderOpen size={15} />, action: props.onLoadSample },
      ],
    },
    {
      label: 'Select',
      items: [
        { label: 'All', icon: <BoxSelect size={15} />, shortcut: '\u2318A', disabled: true },
        { label: 'None', icon: <MousePointerClick size={15} />, shortcut: '\u21E7\u2318A', disabled: true },
        { label: 'Invert', shortcut: '\u2318I', disabled: true },
        { label: '', separator: true },
        { label: 'Lock Selection', icon: <Lock size={15} />, shortcut: 'H', disabled: true },
        { label: 'Unlock All', icon: <Unlock size={15} />, shortcut: '\u21E7H', disabled: true },
        { label: '', separator: true },
        { label: 'Delete Selection', icon: <Trash2 size={15} />, shortcut: 'Delete', disabled: true },
        { label: 'Reset Splat', disabled: true },
        { label: '', separator: true },
        { label: 'Duplicate', icon: <Copy size={15} />, disabled: true },
        { label: 'Separate', icon: <Scissors size={15} />, disabled: true },
      ],
    },
    {
      label: 'Render',
      items: [
        { label: 'Capture Frame', icon: <Camera size={15} />, shortcut: '\u2318P', disabled: true },
        { label: 'Record Video', icon: <Clapperboard size={15} />, disabled: true },
        { label: '', separator: true },
        { label: 'Lighting', icon: <SunMedium size={15} />, disabled: true },
        { label: 'Render Settings', icon: <Settings size={15} />, disabled: true },
      ],
    },
    {
      label: 'Help',
      items: [
        { label: 'Documentation', icon: <BookOpen size={15} /> },
        { label: 'Keyboard Shortcuts', icon: <Keyboard size={15} /> },
        { label: '', separator: true },
        { label: 'About GeoSplat', icon: <Info size={15} /> },
      ],
    },
  ]
}

/* ------------------------------------------------------------------ */
/*  Dropdown                                                           */
/* ------------------------------------------------------------------ */

function MenuDropdown({
  items,
  onClose,
  position,
}: {
  items: MenuItem[]
  onClose: () => void
  position: 'below' | 'right'
}) {
  return (
    <div
      className={`
        absolute ${position === 'below' ? 'top-full left-1/2 -translate-x-1/2 mt-3' : 'left-full top-0 -mt-1 ml-0'}
        min-w-[230px] py-1.5
        bg-[rgba(14,14,20,0.92)] border border-[#2a2a3e] rounded-xl
        shadow-2xl shadow-black/60
        backdrop-blur-xl
        z-[100] animate-fade-in
      `}
    >
      {items.map((item, i) =>
        item.separator ? (
          <div key={i} className="h-px bg-[#2a2a3e] my-1.5 mx-3" />
        ) : (
          <MenuItemRow key={item.label + i} item={item} onClose={onClose} />
        ),
      )}
    </div>
  )
}

function MenuItemRow({ item, onClose }: { item: MenuItem; onClose: () => void }) {
  const [subOpen, setSubOpen] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const handleEnter = () => {
    if (item.children) {
      clearTimeout(timerRef.current)
      setSubOpen(true)
    }
  }
  const handleLeave = () => {
    timerRef.current = setTimeout(() => setSubOpen(false), 150)
  }

  return (
    <div
      className="relative"
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
    >
      <button
        disabled={item.disabled}
        onClick={() => {
          if (item.action) {
            item.action()
            onClose()
          }
        }}
        className={`
          w-full flex items-center gap-2.5 px-3.5 py-2 text-[13.5px] text-left focus-ring
          ${item.disabled
            ? 'text-[#55556a] cursor-default'
            : 'text-[#c8c8d8] hover:bg-[rgba(52,200,255,.08)] hover:text-white cursor-pointer'}
          transition-colors duration-100
        `}
      >
        <span className="w-5 flex-shrink-0 flex justify-center opacity-70">
          {item.icon ?? null}
        </span>
        <span className="flex-1">{item.label}</span>
        {item.shortcut && (
          <span className="text-xs text-[#55556a] ml-4">{item.shortcut}</span>
        )}
        {item.children && <ChevronRight size={13} className="text-[#55556a]" />}
      </button>
      {item.children && subOpen && (
        <MenuDropdown items={item.children} onClose={onClose} position="right" />
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Animated nav link (inspired by 21st.dev Mini Navbar)               */
/* ------------------------------------------------------------------ */

function AnimatedNavLink({
  label,
  isActive,
  onClick,
  onMouseEnter,
  ariaExpanded,
}: {
  label: string
  isActive: boolean
  onClick: () => void
  onMouseEnter: () => void
  ariaExpanded?: boolean
}) {
  return (
    <button
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      aria-expanded={ariaExpanded}
      aria-haspopup="true"
      className="group relative inline-flex items-center overflow-hidden cursor-pointer px-5 py-2 rounded-full transition-all duration-200 focus-ring"
      style={{
        background: isActive ? 'rgba(52,200,255,.1)' : 'transparent',
      }}
    >
      {/* Tube light glow effect on active */}
      {isActive && (
        <div className="absolute inset-0 rounded-full" style={{ boxShadow: '0 0 20px rgba(52,200,255,.15), inset 0 0 12px rgba(52,200,255,.06)' }}>
          <div
            className="absolute top-0 left-1/2 -translate-x-1/2 rounded-full"
            style={{
              width: 28,
              height: 3,
              background: '#34c8ff',
              boxShadow: '0 0 12px 3px rgba(52,200,255,.5), 0 4px 16px rgba(52,200,255,.25)',
            }}
          />
        </div>
      )}

      {/* Animated double-text hover */}
      <div className="flex flex-col transition-transform duration-300 ease-out group-hover:-translate-y-1/2 h-[1.3em] overflow-hidden">
        <span
          className="leading-[1.3em] font-medium tracking-wide transition-colors duration-200"
          style={{
            fontSize: 15,
            color: isActive ? '#34c8ff' : '#9fb0c0',
          }}
        >
          {label}
        </span>
        <span
          className="leading-[1.3em] font-medium tracking-wide"
          style={{ fontSize: 15, color: '#e7edf3' }}
        >
          {label}
        </span>
      </div>
    </button>
  )
}

/* ------------------------------------------------------------------ */
/*  MenuBar                                                            */
/* ------------------------------------------------------------------ */

export default function MenuBar(props: MenuBarProps) {
  const [openMenu, setOpenMenu] = useState<string | null>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const menus = buildMenus(props)

  const close = useCallback(() => setOpenMenu(null), [])

  // Close on outside click
  useEffect(() => {
    if (!openMenu) return
    const handler = (e: MouseEvent) => {
      if (barRef.current && !barRef.current.contains(e.target as Node)) {
        close()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [openMenu, close])

  return (
    <div className="fixed top-5 left-1/2 -translate-x-1/2 z-[10]">
      <div
        ref={barRef}
        className="flex items-center gap-1 select-none rounded-full"
        style={{
          padding: '4px 6px',
          background: 'rgba(14,18,26,.55)',
          border: '1px solid rgba(52,200,255,.12)',
          backdropFilter: 'blur(20px) saturate(1.3)',
          WebkitBackdropFilter: 'blur(20px) saturate(1.3)',
          boxShadow: '0 8px 32px rgba(0,0,0,.4), 0 0 0 1px rgba(255,255,255,.03) inset',
        }}
      >
        {/* Logo dot */}
        <div
          className="flex items-center justify-center mx-2"
          style={{ width: 22, height: 22 }}
        >
          <div
            className="rounded-full"
            style={{
              width: 8,
              height: 8,
              background: '#34c8ff',
              boxShadow: '0 0 10px rgba(52,200,255,.6)',
            }}
          />
        </div>

        {menus.map((menu) => (
          <div key={menu.label} className="relative">
            <AnimatedNavLink
              label={menu.label}
              isActive={openMenu === menu.label}
              onClick={() => setOpenMenu(openMenu === menu.label ? null : menu.label)}
              onMouseEnter={() => { if (openMenu) setOpenMenu(menu.label) }}
              ariaExpanded={openMenu === menu.label}
            />
            {openMenu === menu.label && (
              <MenuDropdown items={menu.items} onClose={close} position="below" />
            )}
          </div>
        ))}

        {/* Separator */}
        <div
          className="mx-1"
          style={{ width: 1, height: 20, background: 'rgba(255,255,255,.08)' }}
        />

        {/* Version badge */}
        <div
          className="flex items-center mx-2 rounded-full"
          style={{
            padding: '3px 10px',
            fontSize: 11,
            fontWeight: 600,
            color: '#5d6b7a',
            background: 'rgba(255,255,255,.04)',
            border: '1px solid rgba(255,255,255,.06)',
          }}
        >
          v0.1
        </div>
      </div>
    </div>
  )
}
