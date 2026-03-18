// ui/Sidebar.tsx
import { useState, useRef, useEffect } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { MessageSquare, Library, Plug, RefreshCw, Settings, Brain, ChevronDown, ChevronRight, Plus, Trash2, GripVertical } from 'lucide-react'
import { useStatsStore, useSessionStore } from '../store'
import { cx } from '../utils'

const NAV = [
  { to: '/library',   icon: Library,       label: '记忆库' },
  { to: '/platforms', icon: Plug,          label: '平台接入' },
  { to: '/sync',      icon: RefreshCw,     label: '同步状态' },
  { to: '/settings',  icon: Settings,      label: '系统设置' },
]

const MIN_SIDEBAR_WIDTH = 180
const MAX_SIDEBAR_WIDTH = 400
const DEFAULT_SIDEBAR_WIDTH = 220

export default function Sidebar() {
  const stats = useStatsStore((s) => s.stats)
  const navigate = useNavigate()
  const { sessions, currentSessionId, createSession, deleteSession, switchSession } = useSessionStore()
  const [chatExpanded, setChatExpanded] = useState(true)
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const saved = localStorage.getItem('sidebar-width')
    return saved ? parseInt(saved, 10) : DEFAULT_SIDEBAR_WIDTH
  })
  const isDragging = useRef(false)

  // Update CSS variable when width changes
  useEffect(() => {
    document.documentElement.style.setProperty('--sidebar-w', `${sidebarWidth}px`)
    localStorage.setItem('sidebar-width', String(sidebarWidth))
  }, [sidebarWidth])

  // Handle drag
  const handleMouseDown = () => {
    isDragging.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return
      const newWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, e.clientX))
      setSidebarWidth(newWidth)
    }

    const handleMouseUp = () => {
      isDragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [])

  function handleNewSession() {
    createSession()
    navigate('/')
  }

  function handleSelectSession(sessionId: string) {
    switchSession(sessionId)
    navigate('/')
  }

  return (
    <>
      <aside
        className="fixed left-0 top-0 h-full flex flex-col bg-white border-r border-ink-100 z-40"
        style={{ width: sidebarWidth }}
      >
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-4 py-5 border-b border-ink-100">
          <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center flex-shrink-0">
            <Brain size={16} className="text-white" />
          </div>
          <div>
            <p className="font-display font-semibold text-ink-800 text-sm leading-tight">Memory OS</p>
            <p className="text-[10px] text-ink-400 leading-tight">个人知识库</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto scrollbar-none">
          {/* Other Nav Items */}
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              <Icon size={15} />
              {label}
            </NavLink>
          ))}

          {/* Chat Sessions - Expandable - at bottom */}
          <div className="mt-auto pt-3 border-t border-ink-100">
            <button
              onClick={() => { setChatExpanded(!chatExpanded); navigate('/'); }}
              className={cx(
                'nav-item w-full justify-between',
                currentSessionId ? 'active' : ''
              )}
            >
              <span className="flex items-center gap-2">
                <MessageSquare size={15} />
                问答
              </span>
              {chatExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>

            {chatExpanded && (
              <div className="ml-4 mt-1 space-y-0.5">
                {/* New Session Button */}
                <button
                  onClick={handleNewSession}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-ink-500 hover:text-accent hover:bg-accent/5 rounded-lg transition-colors"
                >
                  <Plus size={14} />
                  新建会话
                </button>

                {/* Session List */}
                {sessions.map((session) => (
                  <div
                    key={session.id}
                    className={cx(
                      'group flex items-center gap-2 px-3 py-2 text-xs rounded-lg cursor-pointer transition-colors',
                      currentSessionId === session.id
                        ? 'bg-accent/10 text-accent'
                        : 'text-ink-600 hover:bg-ink-50'
                    )}
                  >
                    <button
                      onClick={() => handleSelectSession(session.id)}
                      className="flex-1 text-left truncate"
                    >
                      {session.name}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        deleteSession(session.id)
                      }}
                      className="opacity-0 group-hover:opacity-100 text-ink-400 hover:text-danger transition-opacity"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}

                {sessions.length === 0 && (
                  <p className="text-[10px] text-ink-400 px-3 py-2">暂无会话</p>
                )}
              </div>
            )}
          </div>
        </nav>

        {/* Stats footer */}
        {stats && (
          <div className="px-4 py-3 border-t border-ink-100">
            <p className="text-[10px] text-ink-400 mb-1.5">记忆库概况</p>
            <p className="text-xl font-display font-semibold text-ink-800 tabular-nums">
              {stats.total.toLocaleString()}
            </p>
            <p className="text-[11px] text-ink-400">条记忆</p>

            {stats.by_platform.slice(0, 4).map((p) => (
              <div key={p.platform} className="flex items-center justify-between mt-1">
                <span className="text-[11px] text-ink-500 truncate max-w-[120px]">{p.platform}</span>
                <span className="text-[11px] font-mono text-ink-400 tabular-nums">{p.count}</span>
              </div>
            ))}
          </div>
        )}
      </aside>

      {/* Resize handle */}
      <div
        className="fixed top-0 h-full w-1 cursor-col-resize hover:bg-accent/30 active:bg-accent/50 z-50"
        style={{ left: sidebarWidth }}
        onMouseDown={handleMouseDown}
      />
    </>
  )
}
