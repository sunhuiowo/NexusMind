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
  const { sessions, currentSessionId, createSession } = useSessionStore()

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

  // Get current session to display
  const currentSession = sessions.find(s => s.id === currentSessionId) || sessions[0]

  if (!currentSession) {
    return null
  }

  return (
    <div className="flex-1 overflow-hidden">
      <ChatPanel sessionId={currentSession.id} />
    </div>
  )
}

function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />

      {/* Main content */}
      <main
        className="flex flex-col overflow-hidden"
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
