# Multi-Chat Panel Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将单会话聊天界面改为 ChatGPT 风格的多会话面板，每个面板独立运行、消息隔离，并实现并发控制

**Architecture:** 采用组件拆分策略 - 从 Chat.tsx 提取 ChatPanel 组件，在 App.tsx 中渲染多个 panel，添加全局 isQuerying 状态控制并发

**Tech Stack:** React 18 + TypeScript + Zustand + Tailwind CSS

---

## File Structure

| 操作 | 文件路径 | 职责 |
|------|----------|------|
| 修改 | `frontend/src/store/index.ts` | 添加全局 isQuerying 状态 |
| 创建 | `frontend/src/components/ChatPanel.tsx` | 独立的会话面板组件 |
| 修改 | `frontend/src/App.tsx` | 渲染多个 ChatPanel |
| 修改 | `frontend/src/pages/Chat.tsx` | 简化为包装器 |
| 修改 | `frontend/src/ui/Sidebar.tsx` | 移除 URL 参数逻辑 |

---

## Chunk 1: Store 改动 - 添加全局并发状态

**Files:**
- Modify: `frontend/src/store/index.ts:1-194`

- [ ] **Step 1: 在 store/index.ts 添加全局 isQuerying 状态**

在文件末尾添加:

```typescript
// ── Global query state (for concurrency control) ─────────────────────────────────
interface GlobalQueryState {
  isQuerying: boolean
  queryingSessionId: string | null
  setQuerying: (isQuerying: boolean, sessionId?: string | null) => void
}

export const useGlobalQueryStore = create<GlobalQueryState>((set) => ({
  isQuerying: false,
  queryingSessionId: null,
  setQuerying: (isQuerying, sessionId = null) =>
    set({ isQuerying, queryingSessionId: isQuerying ? sessionId : null }),
}))
```

- [ ] **Step 2: 验证语法正确**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/store/index.ts
git commit -m "feat: add global isQuerying state for concurrency control"
```

---

## Chunk 2: 创建 ChatPanel 组件

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`
- Test: `frontend/src/pages/Chat.tsx` (手动测试)

- [ ] **Step 1: 从 Chat.tsx 提取 ChatPanel 组件**

创建文件 `frontend/src/components/ChatPanel.tsx`:

```typescript
// components/ChatPanel.tsx
import { useEffect, useRef, useState } from 'react'
import { Brain, Trash2, X } from 'lucide-react'
import { queryMemory } from '../api/apiClient'
import { useChatStore, useToastStore, useSessionStore, useGlobalQueryStore } from '../store'
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
  const { sessions, addMessage: addSessionMessage, updateSessionName, clearCurrentSessionMessages, getCurrentSession } = useSessionStore()
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
```

- [ ] **Step 2: 验证 TypeScript 编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx
git commit -m "feat: create ChatPanel component with session isolation"
```

---

## Chunk 3: 修改 App.tsx - 渲染多个 ChatPanel

**Files:**
- Modify: `frontend/src/App.tsx:1-60`

- [ ] **Step 1: 修改 App.tsx 渲染多个 ChatPanel**

替换 App.tsx 内容:

```typescript
// App.tsx
import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Sidebar from './ui/Sidebar'
import ToastContainer from './ui/Toast'
import ChatPanel from './components/ChatPanel'
import Library from './pages/Library'
import Platforms from './pages/Platforms'
import Sync from './pages/Sync'
import Settings from './pages/Settings'
import { getStats } from './api/apiClient'
import { useStatsStore, useSessionStore } from './store'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

function ChatArea() {
  const setStats = useStatsStore(s => s.setStats)
  const { sessions, createSession } = useSessionStore()

  // Load stats on mount for sidebar
  useEffect(() => {
    getStats().then(setStats).catch(() => {})
  }, [setStats])

  // Create initial session if none exists
  useEffect(() => {
    if (sessions.length === 0) {
      createSession()
    }
  }, [sessions.length, createSession])

  // Render multiple chat panels
  if (sessions.length === 0) {
    return null
  }

  return (
    <div className="flex-1 flex overflow-hidden">
      {sessions.map((session) => (
        <div key={session.id} className="flex-1 min-w-0">
          <ChatPanel sessionId={session.id} />
        </div>
      ))}
    </div>
  )
}

function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />

      {/* Main content */}
      <main
        className="flex-1 flex flex-col overflow-hidden"
        style={{ marginLeft: 'var(--sidebar-w)' }}
      >
        <Routes>
          <Route path="/" element={<ChatArea />} />
          <Route path="/library" element={<Library />} />
          <Route path="/platforms" element={<Platforms />} />
          <Route path="/sync" element={<Sync />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <ToastContainer />
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

- [ ] **Step 2: 验证 TypeScript 编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: render multiple ChatPanel components in App"
```

---

## Chunk 4: 简化 Sidebar - 移除 URL 参数逻辑

**Files:**
- Modify: `frontend/src/ui/Sidebar.tsx:1-144`

- [ ] **Step 1: 简化 Sidebar - 移除 URL 参数相关代码**

修改 `handleNewSession` 和 `handleSelectSession` 函数:

```typescript
// 替换这两个函数
function handleNewSession() {
  createSession()
}

function handleSelectSession(sessionId: string) {
  switchSession(sessionId)
}
```

移除 `import { useNavigate } from 'react-router-dom'`

- [ ] **Step 2: 验证 TypeScript 编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/ui/Sidebar.tsx
git commit -m "refactor: simplify Sidebar by removing URL parameter logic"
```

---

## Chunk 5: 清理 Chat.tsx（可选）

**Files:**
- Modify: `frontend/src/pages/Chat.tsx:1-263`

- [ ] **Step 1: 简化 Chat.tsx 为包装器**

由于 ChatPanel 已独立，可以简化 Chat.tsx 或直接删除（取决于是否还有其他地方使用）

可以保留作为向后兼容:

```typescript
// pages/Chat.tsx
// 已迁移到 ChatPanel 组件，此文件保留作为路由兼容
import { useParams } from 'react-router-dom'
import ChatPanel from '../components/ChatPanel'

export default function Chat() {
  const { session } = useParams()
  return <ChatPanel sessionId={session || ''} />
}
```

或者直接删除此文件并更新 App.tsx 路由。

- [ ] **Step 2: 验证 TypeScript 编译**

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Chat.tsx
git commit -m "refactor: simplify Chat.tsx to wrapper component"
```

---

## 手动测试步骤

完成所有步骤后，手动测试:

1. **启动应用**
   ```bash
   cd frontend && npm run dev
   ```

2. **测试多会话**
   - 点击侧边栏「新建会话」
   - 确认主区域出现新的 panel
   - 确认两个 panel 都有独立的输入框

3. **测试并发控制**
   - 在 Session 1 输入内容并发送
   - 确认 Session 2 的输入框被禁用
   - 确认 Session 2 显示 "会话 1 正在查询中"
   - 等待查询完成，确认 Session 2 恢复

4. **测试消息隔离**
   - 在 Session 1 发送消息
   - 在 Session 2 发送不同消息
   - 确认两个会话的消息独立显示

5. **测试持久化**
   - 刷新页面
   - 确认所有会话和消息保留

---

## 总结

完成所有 Chunk 后，系统将支持:
- ✅ 多个垂直堆叠的会话面板
- ✅ 每个面板独立的滚动区和输入框
- ✅ 消息完全隔离
- ✅ 并发控制（禁用其他会话输入框）
- ✅ localStorage 持久化
