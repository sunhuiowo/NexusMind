// api/types.ts — v1.2.0
export type MediaType = 'text' | 'video' | 'audio' | 'image' | 'repo' | 'pdf'
export type QueryIntent = 'search' | 'recent' | 'summary' | 'platform' | 'related' | 'complex'
export type PlatformId = 'youtube' | 'twitter' | 'github' | 'pocket' | 'bilibili' | 'wechat' | 'douyin' | 'xiaohongshu'
export type AuthStatus = 'connected' | 'needs_reauth' | 'disconnected' | 'error'
export type AuthMode = 'oauth2' | 'qrcode' | 'cookie' | 'pat' | 'apikey'

export interface MemoryCard {
  platform_name: string; title: string; summary: string
  bookmarked_at: string; source_url: string; author?: string
  media_type?: MediaType; tags?: string[]; importance?: number
  relevance_score?: number; thumbnail_url?: string; memory_id?: string
}
export interface QueryResult {
  hits: MemoryCard[]; overall_summary: string; total_found: number
  query_intent: QueryIntent; time_range?: string; thinking?: string
}
export interface MemoryListResult {
  items: MemoryCard[]; total: number; page: number; page_size: number; has_more: boolean
}
export interface StatsResult {
  total: number
  by_platform: { platform: string; count: number }[]
  by_media_type: { type: string; count: number }[]
}
export interface PlatformStatus {
  platform?: string; auth_mode?: AuthMode; status: AuthStatus
  expires_at?: string; last_refresh?: string; scope?: string
}
export interface SyncResult {
  platform: string; success: boolean; added: number; skipped: number; errors: number; error_msg?: string
}
export interface ChatMessage {
  id: string; role: 'user' | 'assistant'; content: string; result?: QueryResult; timestamp: number
  thinking?: string
}
export interface QRCodeResult {
  qrcode_key: string; qrcode_url: string; qrcode_image_b64: string; expires_in: number; error?: string
}
export interface QRPollResult {
  status: 'waiting' | 'scanned' | 'confirmed' | 'expired' | 'error'; error?: string
}
export type ConfigMap = Record<string, string | number | boolean | string[]>
export interface LLMTestResult {
  ok: boolean; provider: string; model?: string; response?: string; error?: string; dim?: number
}
