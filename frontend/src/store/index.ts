// store/index.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { shallow } from 'zustand/shallow'
import type { ChatMessage, StatsResult, PlatformStatus, SyncResult } from '../api/types'

// Re-export shallow for use in components
export { shallow }

// ── Session store (with user isolation) ─────────────────────────────────
export interface ChatSession {
  id: string
  name: string
  messages: ChatMessage[]
  created_at: number
  updated_at: number
}

// All sessions stored in a single object, keyed by userId
// This ensures complete data isolation between users
interface UserSessions {
  sessions: ChatSession[]
  currentSessionId: string | null
}

interface AllUserSessions {
  [userId: string]: UserSessions
}

interface SessionState {
  // Current user ID for session isolation
  currentUserId: string | null
  // Getter returns sessions for current user only
  getSessions: () => ChatSession[]
  getCurrentSessionId: () => string | null
  createSession: () => string  // returns new session id
  deleteSession: (id: string) => void
  switchSession: (id: string) => void
  getCurrentSession: () => ChatSession | null
  addMessage: (msg: ChatMessage) => void
  addMessageToSession: (sessionId: string, msg: ChatMessage) => void
  updateMessageInSession: (sessionId: string, msgId: string, updates: Partial<ChatMessage>) => void
  updateSessionName: (id: string, name: string) => void
  clearCurrentSession: () => void
  clearCurrentSessionMessages: () => void
  // Set current user (called on login)
  setCurrentUser: (userId: string | null) => void
  // Clear all sessions for current user (called on logout)
  clearCurrentUserSessions: () => void
}

const generateSessionId = () => `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`

// Helper to get user ID from auth store
const getCurrentUserId = (): string | null => {
  try {
    const stored = localStorage.getItem('auth-storage')
    if (stored) {
      const parsed = JSON.parse(stored)
      return parsed.state?.userId || null
    }
  } catch {}
  return null
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
      currentUserId: null,

      getSessions: () => {
        const { currentUserId, ...rest } = get()
        // Use auth store userId if not set in session store
        const userId = currentUserId || getCurrentUserId()
        if (!userId) return []

        const allSessions = (rest as unknown as { allUserSessions: AllUserSessions }).allUserSessions
        return allSessions?.[userId]?.sessions || []
      },

      getCurrentSessionId: () => {
        const { currentUserId, ...rest } = get()
        const userId = currentUserId || getCurrentUserId()
        if (!userId) return null

        const allSessions = (rest as unknown as { allUserSessions: AllUserSessions }).allUserSessions
        return allSessions?.[userId]?.currentSessionId || null
      },

      setCurrentUser: (userId: string | null) => {
        set({ currentUserId: userId })
      },

      clearCurrentUserSessions: () => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const newAllSessions = { ...allSessions }
          delete newAllSessions[userId]
          return { allUserSessions: newAllSessions } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },

      createSession: () => {
        const userId = getCurrentUserId()
        if (!userId) return ''

        const id = generateSessionId()
        const newSession: ChatSession = {
          id,
          name: '新对话',
          messages: [],
          created_at: Date.now(),
          updated_at: Date.now(),
        }

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          return {
            allUserSessions: {
              ...allSessions,
              [userId]: {
                sessions: [newSession, ...userSessions.sessions],
                currentSessionId: id,
              }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })

        return id
      },

      deleteSession: (id: string) => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          const newSessions = userSessions.sessions.filter((session) => session.id !== id)
          const newCurrentId = userSessions.currentSessionId === id
            ? (newSessions[0]?.id ?? null)
            : userSessions.currentSessionId
          return {
            allUserSessions: {
              ...allSessions,
              [userId]: { sessions: newSessions, currentSessionId: newCurrentId }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },

      switchSession: (id: string) => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          return {
            allUserSessions: {
              ...allSessions,
              [userId]: { ...userSessions, currentSessionId: id }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },

      getCurrentSession: () => {
        const userId = getCurrentUserId()
        if (!userId) return null

        const s = get()
        const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
        const userSessions = allSessions[userId]
        if (!userSessions) return null

        return userSessions.sessions.find((session) => session.id === userSessions.currentSessionId) || null
      },

      addMessage: (msg: ChatMessage) => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          if (!userSessions.currentSessionId) return s as unknown as Pick<SessionState, 'currentUserId'>

          return {
            allUserSessions: {
              ...allSessions,
              [userId]: {
                ...userSessions,
                sessions: userSessions.sessions.map((session) =>
                  session.id === userSessions.currentSessionId
                    ? { ...session, messages: [...session.messages, msg], updated_at: Date.now() }
                    : session
                ),
              }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },

      addMessageToSession: (sessionId: string, msg: ChatMessage) => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          return {
            allUserSessions: {
              ...allSessions,
              [userId]: {
                ...userSessions,
                sessions: userSessions.sessions.map((session) =>
                  session.id === sessionId
                    ? { ...session, messages: [...session.messages, msg], updated_at: Date.now() }
                    : session
                ),
              }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },

      updateMessageInSession: (sessionId: string, msgId: string, updates: Partial<ChatMessage>) => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          return {
            allUserSessions: {
              ...allSessions,
              [userId]: {
                ...userSessions,
                sessions: userSessions.sessions.map((session) =>
                  session.id === sessionId
                    ? {
                        ...session,
                        messages: session.messages.map((msg) =>
                          msg.id === msgId ? { ...msg, ...updates } : msg
                        ),
                        updated_at: Date.now()
                      }
                    : session
                ),
              }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },

      updateSessionName: (id: string, name: string) => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          return {
            allUserSessions: {
              ...allSessions,
              [userId]: {
                ...userSessions,
                sessions: userSessions.sessions.map((session) =>
                  session.id === id ? { ...session, name } : session
                ),
              }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },

      clearCurrentSession: () => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          return {
            allUserSessions: {
              ...allSessions,
              [userId]: { ...userSessions, currentSessionId: null }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },

      clearCurrentSessionMessages: () => {
        const userId = getCurrentUserId()
        if (!userId) return

        set((s) => {
          const allSessions = (s as unknown as { allUserSessions: AllUserSessions }).allUserSessions || {}
          const userSessions = allSessions[userId] || { sessions: [], currentSessionId: null }
          return {
            allUserSessions: {
              ...allSessions,
              [userId]: {
                ...userSessions,
                sessions: userSessions.sessions.map((session) =>
                  session.id === userSessions.currentSessionId
                    ? { ...session, messages: [], updated_at: Date.now() }
                    : session
                ),
              }
            }
          } as unknown as Pick<SessionState, 'currentUserId'>
        })
      },
    }),
    {
      name: 'chat-sessions',
      partialize: (state) => {
        // Only persist allUserSessions, currentUserId is derived from auth
        const s = state as unknown as { allUserSessions?: AllUserSessions; currentUserId?: string }
        return { allUserSessions: s.allUserSessions || {} }
      },
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

// ── Auth store (user session management) ───────────────────────────────────────
interface AuthState {
  isAuthenticated: boolean
  isRegistered: boolean
  username: string | null
  userId: string | null
  sessionId: string | null
  isAdmin: boolean
  login: (username: string, password: string) => Promise<{ success: boolean; error?: string }>
  register: (username: string, password: string, confirmPassword: string) => Promise<{ success: boolean; error?: string }>
  logout: () => Promise<void>
  fetchMe: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      isAuthenticated: false,
      isRegistered: false,
      username: null,
      userId: null,
      sessionId: null,
      isAdmin: false,

      register: async (username: string, password: string, confirmPassword: string) => {
        if (!username || username.trim().length < 2) {
          return { success: false, error: '用户名至少需要2个字符' }
        }
        if (!password || password.length < 4) {
          return { success: false, error: '密码至少需要4个字符' }
        }
        if (password !== confirmPassword) {
          return { success: false, error: '两次输入的密码不一致' }
        }

        try {
          const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
          })
          const data = await response.json()

          if (!response.ok) {
            return { success: false, error: data.detail || '注册失败' }
          }

          // Auto login after successful registration
          return get().login(username, password)
        } catch (error) {
          return { success: false, error: '网络错误，请重试' }
        }
      },

      login: async (username: string, password: string) => {
        try {
          const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
          })
          const data = await response.json()

          if (!response.ok) {
            return { success: false, error: data.detail || '登录失败' }
          }

          set({
            isAuthenticated: true,
            isRegistered: true,
            username: data.username,
            userId: data.user_id,
            sessionId: data.session_id,
            isAdmin: data.is_admin,
          })

          return { success: true }
        } catch (error) {
          return { success: false, error: '网络错误，请重试' }
        }
      },

      logout: async () => {
        const { sessionId } = get()
        if (sessionId) {
          try {
            await fetch('/api/auth/logout', {
              method: 'POST',
              headers: { 'X-Session-Id': sessionId }
            })
          } catch {
            // Ignore logout errors
          }
        }

        set({
          isAuthenticated: false,
          username: null,
          userId: null,
          sessionId: null,
          isAdmin: false,
        })
      },

      fetchMe: async () => {
        const { sessionId } = get()
        if (!sessionId) return

        try {
          const response = await fetch('/api/auth/me', {
            headers: { 'X-Session-Id': sessionId }
          })
          if (response.ok) {
            const data = await response.json()
            set({
              isAuthenticated: true,
              username: data.username,
              userId: data.id,
              isAdmin: data.is_admin,
            })
          } else {
            set({
              isAuthenticated: false,
              sessionId: null,
            })
          }
        } catch {
          // Ignore errors
        }
      },
    }),
    {
      name: 'auth-storage',
    }
  )
)
