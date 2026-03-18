// components/ChatPanel.tsx
import { useEffect, useRef, useState } from 'react'
import { Brain, Trash2, X } from 'lucide-react'
import { queryMemory } from '../api/apiClient'
import { useToastStore, useSessionStore, useGlobalQueryStore } from '../store'
import ChatInput from './ChatInput'
import QueryResultCard from './QueryResultCard'
import type { ChatMessage } from '../api/types'
import { cx } from '../utils'

const CONVERSATION_HISTORY_LIMIT = 10

function UserBubble({ msg }: { msg: ChatMessage }) {
  return (
    <div className="flex justify-end animate-fade-in">
      <div className="max-w-[75%] bg-accent text-white px-4 py-2.5 rounded-2xl rounded-tr-sm text-sm leading-relaxed shadow-sm shadow-accent/20">
        {msg.content}
      </div>
    </div>
  )
}

function AssistantBubble({ msg, showThinking = true }: { msg: ChatMessage; showThinking?: boolean }) {
  return (
    <div className="flex gap-3 animate-slide-up">
      <div className="w-7 h-7 rounded-lg bg-ink-100 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Brain size={14} className="text-ink-500" />
      </div>
      <div className="flex-1 min-w-0">
        {msg.result ? (
          <QueryResultCard result={msg.result} thinking={msg.thinking} showThinking={showThinking} />
        ) : (
          <p className="text-sm text-ink-600 leading-relaxed">{msg.content}</p>
        )}
        <p className="text-[10px] text-ink-300 mt-1.5">
          {new Date(msg.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>
    </div>
  )
}

function ThinkingBubble() {
  return (
    <div className="flex gap-3 animate-fade-in">
      <div className="w-7 h-7 rounded-lg bg-ink-100 flex items-center justify-center flex-shrink-0">
        <Brain size={14} className="text-ink-500 animate-pulse-soft" />
      </div>
      <div className="flex items-center gap-1.5 py-2">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="w-1.5 h-1.5 bg-ink-300 rounded-full animate-bounce"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </div>
    </div>
  )
}

interface ChatPanelProps {
  sessionId: string
  onClose?: () => void
}

export default function ChatPanel({ sessionId, onClose }: ChatPanelProps) {
  const { sessions, addMessage: addSessionMessage, updateSessionName, clearCurrentSessionMessages } = useSessionStore()
  const { isQuerying, queryingSessionId, setQuerying } = useGlobalQueryStore()

  const push = useToastStore((s) => s.push)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [showThinking, setShowThinking] = useState(true)

  // Get session from store
  const session = sessions.find(s => s.id === sessionId)
  const messages = session?.messages ?? []

  // Determine if this panel is disabled
  const isDisabled = isQuerying && queryingSessionId !== sessionId
  const queryingSessionName = sessions.find(s => s.id === queryingSessionId)?.name ?? '未知会话'

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  // Generate session name from first user message
  useEffect(() => {
    if (messages.length > 0 && session?.name === '新对话') {
      const firstUserMsg = messages.find(m => m.role === 'user')
      if (firstUserMsg && firstUserMsg.content.length > 0) {
        const name = firstUserMsg.content.slice(0, 15) + (firstUserMsg.content.length > 15 ? '...' : '')
        updateSessionName(sessionId, name)
      }
    }
  }, [messages, sessionId, session?.name])

  // Build conversation history for context
  const getConversationHistory = () => {
    const history: { role: 'user' | 'assistant'; content: string }[] = []
    const recentMessages = messages.slice(-CONVERSATION_HISTORY_LIMIT)
    for (const msg of recentMessages) {
      if (msg.role === 'user' || msg.role === 'assistant') {
        const content = msg.result?.overall_summary || msg.content
        history.push({ role: msg.role, content })
      }
    }
    return history
  }

  async function handleQuery(query: string) {
    // Set querying state
    setQuerying(true, sessionId)

    // Add user message
    const userMsg: ChatMessage = {
      id: Math.random().toString(36).slice(2),
      role: 'user',
      content: query,
      timestamp: Date.now(),
    }
    addSessionMessage(userMsg)

    try {
      const conversationHistory = getConversationHistory()
      const result = await queryMemory(query, false, conversationHistory)
      const assistantMsg: ChatMessage = {
        id: Math.random().toString(36).slice(2),
        role: 'assistant',
        content: result.overall_summary || `找到 ${result.total_found} 条相关收藏`,
        result,
        thinking: result.thinking,
        timestamp: Date.now(),
      }
      addSessionMessage(assistantMsg)
    } catch (err) {
      const errorMsg: ChatMessage = {
        id: Math.random().toString(36).slice(2),
        role: 'assistant',
        content: '查询失败，请检查后端服务是否运行中。',
        timestamp: Date.now(),
      }
      addSessionMessage(errorMsg)
      push('查询失败，请检查后端连接', 'error')
    } finally {
      setQuerying(false)
    }
  }

  function handleClear() {
    clearCurrentSessionMessages()
  }

  return (
    <div className="flex flex-col h-full border-r border-ink-100 last:border-r-0">
      {/* Topbar */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-ink-100 bg-white/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex items-center gap-3">
          {onClose && (
            <button
              onClick={onClose}
              className="p-1 rounded-lg hover:bg-ink-100 text-ink-400 hover:text-ink-600 transition-colors"
            >
              <X size={16} />
            </button>
          )}
          <div>
            <h1 className="font-display font-semibold text-ink-800">
              {session?.name || '问答'}
            </h1>
            <p className="text-xs text-ink-400 mt-0.5">和你的收藏库对话</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Thinking toggle */}
          <button
            onClick={() => setShowThinking(!showThinking)}
            className={cx(
              'text-xs px-2.5 py-1 rounded-lg border transition-all flex items-center gap-1.5',
              showThinking
                ? 'bg-accent text-white border-accent'
                : 'border-ink-200 text-ink-500 hover:border-ink-300'
            )}
          >
            <Brain size={12} />
            {showThinking ? '显示思考' : '隐藏思考'}
          </button>
          {messages.length > 0 && (
            <button onClick={handleClear} className="btn-ghost text-xs gap-1">
              <Trash2 size={13} />
              清空对话
            </button>
          )}
        </div>
      </header>

      {/* Disabled overlay message */}
      {isDisabled && (
        <div className="px-6 py-2 bg-amber-50 border-b border-amber-200 text-amber-700 text-xs flex items-center gap-2">
          <span>⚠️</span>
          <span>会话「{queryingSessionName}」正在查询中，请稍候...</span>
        </div>
      )}

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5 scrollbar-none">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center py-16 animate-fade-in">
            <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center mb-4">
              <Brain size={28} className="text-accent" />
            </div>
            <h2 className="font-display text-xl font-semibold text-ink-700 mb-2">你好！</h2>
            <p className="text-sm text-ink-400 max-w-sm leading-relaxed">
              我是你的个人记忆助手。输入任何问题，我会从你的跨平台收藏中找到相关内容并总结。
            </p>
          </div>
        )}

        {messages.map((msg) =>
          msg.role === 'user'
            ? <UserBubble key={msg.id} msg={msg} />
            : <AssistantBubble key={msg.id} msg={msg} showThinking={showThinking} />
        )}

        {isQuerying && queryingSessionId === sessionId && <ThinkingBubble />}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-ink-100 bg-white/80 backdrop-blur-sm">
        <ChatInput
          onSubmit={handleQuery}
          loading={isQuerying && queryingSessionId === sessionId}
          disabled={isDisabled}
        />
      </div>
    </div>
  )
}
