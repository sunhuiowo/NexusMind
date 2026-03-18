// store/index.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ChatMessage, StatsResult, PlatformStatus, SyncResult } from '../api/types'

// ── Session store (with localStorage persistence) ─────────────────────────────────
export interface ChatSession {
  id: string
  name: string
  messages: ChatMessage[]
  created_at: number
  updated_at: number
}

interface SessionState {
  sessions: ChatSession[]
  currentSessionId: string | null
  createSession: () => string  // returns new session id
  deleteSession: (id: string) => void
  switchSession: (id: string) => void
  getCurrentSession: () => ChatSession | null
  addMessage: (msg: ChatMessage) => void
  addMessageToSession: (sessionId: string, msg: ChatMessage) => void
  updateSessionName: (id: string, name: string) => void
  clearCurrentSession: () => void
  clearCurrentSessionMessages: () => void
}

const generateSessionId = () => `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`

export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
      sessions: [],
      currentSessionId: null,

      createSession: () => {
        const id = generateSessionId()
        const newSession: ChatSession = {
          id,
          name: '新对话',
          messages: [],
          created_at: Date.now(),
          updated_at: Date.now(),
        }
        set((s) => ({
          sessions: [newSession, ...s.sessions],
          currentSessionId: id,
        }))
        return id
      },

      deleteSession: (id: string) => {
        set((s) => {
          const newSessions = s.sessions.filter((session) => session.id !== id)
          const newCurrentId = s.currentSessionId === id
            ? (newSessions[0]?.id ?? null)
            : s.currentSessionId
          return { sessions: newSessions, currentSessionId: newCurrentId }
        })
      },

      switchSession: (id: string) => {
        set({ currentSessionId: id })
      },

      getCurrentSession: () => {
        const s = get()
        return s.sessions.find((session) => session.id === s.currentSessionId) ?? null
      },

      addMessage: (msg: ChatMessage) => {
        set((s) => {
          if (!s.currentSessionId) return s
          return {
            sessions: s.sessions.map((session) =>
              session.id === s.currentSessionId
                ? { ...session, messages: [...session.messages, msg], updated_at: Date.now() }
                : session
            ),
          }
        })
      },

      addMessageToSession: (sessionId: string, msg: ChatMessage) => {
        set((s) => ({
          sessions: s.sessions.map((session) =>
            session.id === sessionId
              ? { ...session, messages: [...session.messages, msg], updated_at: Date.now() }
              : session
          ),
        }))
      },

      updateSessionName: (id: string, name: string) => {
        set((s) => ({
          sessions: s.sessions.map((session) =>
            session.id === id ? { ...session, name } : session
          ),
        }))
      },

      clearCurrentSession: () => {
        set({ currentSessionId: null })
      },

      clearCurrentSessionMessages: () => {
        set((s) => ({
          sessions: s.sessions.map((session) =>
            session.id === s.currentSessionId
              ? { ...session, messages: [], updated_at: Date.now() }
              : session
          ),
        }))
      },
    }),
    {
      name: 'chat-sessions',
    }
  )
)

// ── Chat store (legacy - for current session only) ───────────────────────────────
interface ChatState {
  messages: ChatMessage[]
  loading: boolean
  addMessage: (msg: ChatMessage) => void
  setLoading: (v: boolean) => void
  clear: () => void
  setMessages: (msgs: ChatMessage[]) => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  loading: false,
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  setLoading: (v) => set({ loading: v }),
  clear: () => set({ messages: [] }),
  setMessages: (msgs) => set({ messages: msgs }),
}))

// ── Stats store ───────────────────────────────────────────────────────────────
interface StatsState {
  stats: StatsResult | null
  setStats: (s: StatsResult) => void
}

export const useStatsStore = create<StatsState>((set) => ({
  stats: null,
  setStats: (stats) => set({ stats }),
}))

// ── Platform store ────────────────────────────────────────────────────────────
interface PlatformState {
  statuses: Record<string, PlatformStatus>
  setStatuses: (s: Record<string, PlatformStatus>) => void
  updateStatus: (platform: string, status: Partial<PlatformStatus>) => void
}

export const usePlatformStore = create<PlatformState>((set) => ({
  statuses: {},
  setStatuses: (statuses) => set({ statuses }),
  updateStatus: (platform, status) =>
    set((s) => ({
      statuses: {
        ...s.statuses,
        [platform]: { ...s.statuses[platform], ...status },
      },
    })),
}))

// ── Sync store ────────────────────────────────────────────────────────────────
interface SyncState {
  syncing: boolean
  lastResults: SyncResult[]
  setSyncing: (v: boolean) => void
  setResults: (r: SyncResult[]) => void
}

export const useSyncStore = create<SyncState>((set) => ({
  syncing: false,
  lastResults: [],
  setSyncing: (v) => set({ syncing: v }),
  setResults: (r) => set({ lastResults: r }),
}))

// ── Toast store ───────────────────────────────────────────────────────────────
export type ToastType = 'success' | 'error' | 'info' | 'warning'
interface Toast { id: string; message: string; type: ToastType }
interface ToastState {
  toasts: Toast[]
  push: (message: string, type?: ToastType) => void
  remove: (id: string) => void
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (message, type = 'info') => {
    const id = Math.random().toString(36).slice(2)
    set((s) => ({ toasts: [...s.toasts, { id, message, type }] }))
    setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 3500)
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

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
