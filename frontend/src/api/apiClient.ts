// api/apiClient.ts — v1.2.0 完整版
import axios from 'axios'
import type {
  QueryResult, StatsResult, PlatformStatus, MemoryListResult,
  QRCodeResult, QRPollResult, ConfigMap, LLMTestResult
} from './types'

const http = axios.create({ baseURL: '/api', timeout: 60000, headers: { 'Content-Type': 'application/json' } })

// ── Query ──────────────────────────────────────────────────────────────────
export interface ConversationHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export const queryMemory = async (
  query: string,
  voice = false,
  conversationHistory?: ConversationHistoryItem[]
): Promise<QueryResult> =>
  (await http.post<QueryResult>('/query', { query, voice, conversation_history: conversationHistory })).data

// ── Memories list (真实分页) ───────────────────────────────────────────────
export interface ListMemoriesParams {
  platform?: string; media_type?: string; days?: number
  tags?: string; query?: string; page?: number; page_size?: number
  order_by?: 'bookmarked_at' | 'importance'
}
export const listMemories = async (params: ListMemoriesParams = {}): Promise<MemoryListResult> =>
  (await http.get<MemoryListResult>('/memories', { params })).data

// ── Stats ──────────────────────────────────────────────────────────────────
export const getStats = async (platform?: string): Promise<StatsResult> =>
  (await http.get<StatsResult>('/memories/stats', { params: platform ? { platform } : undefined })).data

// ── Memory actions ─────────────────────────────────────────────────────────
export const getMemory = async (id: string) => (await http.get(`/memories/${id}`)).data
export const getRelated = async (id: string, top_k = 5): Promise<QueryResult> =>
  (await http.get<QueryResult>(`/memories/${id}/related`, { params: { top_k } })).data
export const searchByTags = async (tags: string[], match_mode: 'any' | 'all' = 'any'): Promise<QueryResult> =>
  (await http.post<QueryResult>('/memories/search/tags', { tags, match_mode })).data
export const deleteMemory = async (id: string): Promise<void> => { await http.delete(`/memories/${id}`) }
export const markImportant = async (id: string): Promise<void> => { await http.post(`/memories/${id}/important`) }
export const updateImportance = async (id: string, delta?: number, setValue?: number) =>
  http.patch(`/memories/${id}/importance`, { delta, set_value: setValue })

// ── Sync ───────────────────────────────────────────────────────────────────
export const syncPlatform = async (platform?: string, fullSync = false) =>
  (await http.post('/sync', { platform: platform ?? null, full_sync: fullSync })).data

// ── Resync (重新同步：先删除后全量同步) ─────────────────────────────────────
export const resyncPlatform = async (platform?: string) =>
  (await http.post('/resync', { platform: platform ?? null })).data

// ── Auth: status ───────────────────────────────────────────────────────────
export const getAuthStatus = async (): Promise<Record<string, PlatformStatus>> =>
  (await http.get<Record<string, PlatformStatus>>('/auth/status')).data

// OAuth (YouTube / Twitter / Pocket)
export const getAuthUrl = async (platform: string): Promise<{ auth_url: string; state: string }> =>
  (await http.get(`/auth/${platform}/connect`)).data

// QR code (Bilibili / Douyin)
export const getQRCode = async (platform: string): Promise<QRCodeResult> =>
  (await http.get<QRCodeResult>(`/auth/${platform}/qrcode`)).data
export const pollQRCode = async (platform: string, qrcode_key: string): Promise<QRPollResult> =>
  (await http.get<QRPollResult>(`/auth/${platform}/qrcode/poll`, { params: { qrcode_key } })).data

// Cookie (Xiaohongshu)
export const setXhsCookie = async (cookie: string): Promise<void> =>
  { await http.post('/auth/xiaohongshu/cookie', { cookie }) }

// API Key (WeChat)
export const setWechatKey = async (api_key: string): Promise<void> =>
  { await http.post('/auth/wechat/apikey', { api_key }) }

// PAT (GitHub)
export const setGithubPAT = async (pat: string): Promise<void> =>
  { await http.post('/auth/github/pat', { pat }) }

// Token (Pocket manual)
export const setPocketToken = async (access_token: string, username = ''): Promise<void> =>
  { await http.post('/auth/pocket/token', { access_token, username }) }

// Revoke
export const revokeAuth = async (platform: string): Promise<void> =>
  { await http.delete(`/auth/${platform}`) }

// ── Config ─────────────────────────────────────────────────────────────────
export const getConfig = async (): Promise<ConfigMap> =>
  (await http.get<ConfigMap>('/config')).data
export const postConfig = async (updates: ConfigMap): Promise<void> =>
  { await http.post('/config', { updates }) }
export const testLLM = async (): Promise<LLMTestResult> =>
  (await http.get<LLMTestResult>('/config/test-llm')).data
export const testEmbedding = async (): Promise<LLMTestResult> =>
  (await http.get<LLMTestResult>('/config/test-embedding')).data

// ── Health ─────────────────────────────────────────────────────────────────
export const checkHealth = async (): Promise<boolean> => {
  try { await http.get('/health'); return true } catch { return false }
}

export default http
