// utils/index.ts
import type { MediaType, PlatformId } from '../api/types'

export function cx(...classes: (string | undefined | false | null)[]): string {
  return classes.filter(Boolean).join(' ')
}

export function formatDate(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

export function relativeTime(iso: string): string {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  const day = Math.floor(h / 24)
  if (day < 30) return `${day} 天前`
  return formatDate(iso)
}

export function importanceClass(imp: number): string {
  if (imp >= 0.85) return 'imp-top'
  if (imp >= 0.6)  return 'imp-high'
  if (imp >= 0.35) return 'imp-mid'
  return 'imp-low'
}

export function importanceLabel(imp: number): string {
  if (imp >= 0.85) return '核心'
  if (imp >= 0.6)  return '重要'
  if (imp >= 0.35) return '一般'
  return '低'
}

export const MEDIA_LABELS: Record<MediaType, string> = {
  text:  '文章',
  video: '视频',
  audio: '音频',
  image: '图文',
  repo:  '仓库',
  pdf:   'PDF',
}

export const MEDIA_COLORS: Record<MediaType, string> = {
  text:  'bg-blue-50 text-blue-700',
  video: 'bg-red-50 text-red-700',
  audio: 'bg-purple-50 text-purple-700',
  image: 'bg-pink-50 text-pink-700',
  repo:  'bg-ink-100 text-ink-700',
  pdf:   'bg-amber-50 text-amber-700',
}

export const PLATFORM_META: Record<string, { name: string; color: string; emoji: string }> = {
  youtube:     { name: 'YouTube',    color: 'platform-youtube',     emoji: '▶' },
  twitter:     { name: 'Twitter/X',  color: 'platform-twitter',     emoji: '✕' },
  github:      { name: 'GitHub',     color: 'platform-github',      emoji: '⬡' },
  pocket:      { name: 'Pocket',     color: 'platform-pocket',      emoji: '◎' },
  bilibili:    { name: 'Bilibili',   color: 'platform-bilibili',    emoji: '⊙' },
  wechat:      { name: '微信收藏',   color: 'platform-wechat',      emoji: '◈' },
  douyin:      { name: '抖音',       color: 'platform-douyin',      emoji: '♪' },
  xiaohongshu: { name: '小红书',     color: 'platform-xiaohongshu', emoji: '✿' },
}

export const INTENT_LABELS: Record<string, string> = {
  search:   '语义搜索',
  recent:   '时间查询',
  summary:  '主题总结',
  platform: '平台过滤',
  related:  '关联推荐',
  complex:  '复合查询',
}
