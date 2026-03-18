// pages/Platforms.tsx
import { useEffect } from 'react'
import { Plug, RefreshCw } from 'lucide-react'
import { getAuthStatus, getStats } from '../api/apiClient'
import { usePlatformStore, useStatsStore, useToastStore } from '../store'
import PlatformCard from '../components/PlatformCard'

const ALL_PLATFORMS = [
  'youtube', 'twitter', 'github', 'pocket',
  'bilibili', 'wechat', 'douyin', 'xiaohongshu',
]

export default function Platforms() {
  const { statuses, setStatuses } = usePlatformStore()
  const stats = useStatsStore(s => s.stats)
  const setStats = useStatsStore(s => s.setStats)
  const push = useToastStore(s => s.push)

  async function loadData() {
    try {
      const [statusData, statsData] = await Promise.all([getAuthStatus(), getStats()])
      setStatuses(statusData)
      setStats(statsData)
    } catch {
      push('加载平台状态失败', 'error')
    }
  }

  useEffect(() => { loadData() }, [])

  const connectedCount = Object.values(statuses).filter(s => s.status === 'connected').length
  const needsReauthCount = Object.values(statuses).filter(s => s.status === 'needs_reauth').length

  // Build a map: platform -> memory count from stats
  const platformCountMap: Record<string, number> = {}
  stats?.by_platform.forEach(p => {
    const id = Object.entries({
      'YouTube': 'youtube', 'Twitter / X': 'twitter', 'GitHub Star': 'github',
      'Pocket': 'pocket', 'Bilibili': 'bilibili', '微信收藏': 'wechat',
      '抖音': 'douyin', '小红书': 'xiaohongshu',
    }).find(([name]) => p.platform === name)?.[1]
    if (id) platformCountMap[id] = p.count
  })

  return (
    <div className="flex flex-col h-full">
      {/* Topbar */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-ink-100 bg-white/80 backdrop-blur-sm flex-shrink-0">
        <div>
          <h1 className="font-display font-semibold text-ink-800">平台接入</h1>
          <p className="text-xs text-ink-400 mt-0.5">
            {connectedCount} 个已连接
            {needsReauthCount > 0 && <span className="text-warning ml-2">· {needsReauthCount} 个需要重新授权</span>}
          </p>
        </div>
        <button onClick={loadData} className="btn-ghost text-xs gap-1.5">
          <RefreshCw size={13} />
          刷新状态
        </button>
      </header>

      {/* Summary bar */}
      <div className="px-6 py-3 bg-ink-50 border-b border-ink-100 flex-shrink-0">
        <div className="flex gap-4">
          {[
            { label: '已连接', value: connectedCount, color: 'text-success' },
            { label: '需要授权', value: needsReauthCount, color: 'text-warning' },
            { label: '未连接', value: ALL_PLATFORMS.length - connectedCount - needsReauthCount, color: 'text-ink-400' },
          ].map(({ label, value, color }) => (
            <div key={label} className="flex items-center gap-1.5">
              <span className={`text-base font-display font-semibold tabular-nums ${color}`}>{value}</span>
              <span className="text-xs text-ink-400">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Platform grid */}
      <div className="flex-1 overflow-y-auto px-6 py-5 scrollbar-none">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {ALL_PLATFORMS.map(id => (
            <PlatformCard
              key={id}
              platformId={id}
              status={statuses[id] ?? { platform: id, status: 'disconnected' }}
              memCount={platformCountMap[id]}
            />
          ))}
        </div>

        {/* Auth flow info */}
        <div className="mt-6 p-4 rounded-xl bg-ink-50 border border-ink-100">
          <div className="flex items-start gap-2.5">
            <Plug size={14} className="text-ink-400 mt-0.5 flex-shrink-0" />
            <div className="text-xs text-ink-500 space-y-1 leading-relaxed">
              <p className="font-medium text-ink-700">关于平台授权</p>
              <p>OAuth 平台（YouTube、Twitter、GitHub、Bilibili、抖音）：点击「连接」后跳转官方授权页，完成后自动返回。Token 过期前 5 分钟静默刷新，无感知续期。</p>
              <p>小红书：无官方 API，需手动提供登录 Cookie（有效期约 30 天，过期前 7 天提醒更新）。</p>
              <p>微信收藏：需在系统设置中配置企业微信 API Key。</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
