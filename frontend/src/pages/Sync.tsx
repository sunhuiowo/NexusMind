// pages/Sync.tsx
import { useState, useEffect, useMemo } from 'react'
import { RefreshCw, CheckCircle, XCircle, SkipForward, Loader2, Zap, Trash2, AlertTriangle, ChevronDown, ChevronRight, FolderOpen } from 'lucide-react'
import { syncPlatform, resyncPlatform, listMemories } from '../api/apiClient'
import { useSyncStore, useToastStore } from '../store'
import { cx, PLATFORM_META } from '../utils'
import type { SyncResult, MemoryCard } from '../api/types'

const ALL_PLATFORMS = [
  'youtube', 'twitter', 'github', 'pocket',
  'bilibili', 'wechat', 'douyin', 'xiaohongshu',
]

const TIME_RANGES = [
  { value: '1d', label: '近1天' },
  { value: '7d', label: '近7天' },
  { value: '30d', label: '近30天' },
  { value: '1y', label: '近1年' },
  { value: 'all', label: '全部' },
]

const timeRangeToDays: Record<string, number | undefined> = {
  '1d': 1,
  '7d': 7,
  '30d': 30,
  '1y': 365,
  'all': undefined,
}

export default function Sync() {
  const { syncing, lastResults, setSyncing, setResults } = useSyncStore()
  const push = useToastStore(s => s.push)
  const [fullSync, setFullSync] = useState(false)
  const [selectedPlatform, setSelectedPlatform] = useState<string>('')
  const [timeRange, setTimeRange] = useState<string>('all')
  const [liveLog, setLiveLog] = useState<string[]>([])
  const [showResyncConfirm, setShowResyncConfirm] = useState(false)

  // Platform existing memories
  const [platformMemories, setPlatformMemories] = useState<MemoryCard[]>([])
  const [platformMemoriesMap, setPlatformMemoriesMap] = useState<Record<string, MemoryCard[]>>({})
  const [loadingMemories, setLoadingMemories] = useState(false)
  const [showMemoriesDropdown, setShowMemoriesDropdown] = useState(false)
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<Set<string>>(new Set())
  const [expandedPlatforms, setExpandedPlatforms] = useState<Set<string>>(new Set())

  const days = timeRangeToDays[timeRange]

  // Fetch existing memories when platform or time range changes
  useEffect(() => {
    if (!selectedPlatform) {
      // Fetch all platforms' memories
      setLoadingMemories(true)
      const fetchAllPlatforms = async () => {
        const results: Record<string, MemoryCard[]> = {}
        try {
          await Promise.all(
            ALL_PLATFORMS.map(async (platform) => {
              const result = await listMemories({ platform, days, page_size: 100 })
              if (result.items.length > 0) {
                results[platform] = result.items
              }
            })
          )
          setPlatformMemoriesMap(results)
        } catch (err) {
          console.error('Failed to fetch memories:', err)
        } finally {
          setLoadingMemories(false)
        }
      }
      fetchAllPlatforms()
      setPlatformMemories([])
      setSelectedMemoryIds(new Set())
    } else {
      // Fetch selected platform's memories
      async function fetchMemories() {
        setLoadingMemories(true)
        try {
          const result = await listMemories({ platform: selectedPlatform, days, page_size: 100 })
          setPlatformMemories(result.items)
          setPlatformMemoriesMap({})
        } catch (err) {
          console.error('Failed to fetch memories:', err)
          setPlatformMemories([])
        } finally {
          setLoadingMemories(false)
        }
      }
      fetchMemories()
      setSelectedMemoryIds(new Set())
    }
  }, [selectedPlatform, timeRange])

  // Toggle platform expansion in accordion
  function togglePlatformExpand(platform: string) {
    setExpandedPlatforms(prev => {
      const newSet = new Set(prev)
      if (newSet.has(platform)) {
        newSet.delete(platform)
      } else {
        newSet.add(platform)
      }
      return newSet
    })
  }

  function toggleMemorySelection(memoryId: string) {
    setSelectedMemoryIds(prev => {
      const newSet = new Set(prev)
      if (newSet.has(memoryId)) {
        newSet.delete(memoryId)
      } else {
        newSet.add(memoryId)
      }
      return newSet
    })
  }

  function selectAllMemories() {
    const allMemories = selectedPlatform ? platformMemories : Object.values(platformMemoriesMap).flat()
    const allIds = allMemories.map(m => m.memory_id || '').filter(Boolean)

    if (selectedMemoryIds.size === allIds.length) {
      setSelectedMemoryIds(new Set())
    } else {
      setSelectedMemoryIds(new Set(allIds))
    }
  }

  async function handleSync() {
    if (syncing) return
    setSyncing(true)
    setLiveLog([])
    setResults([])

    const platforms = selectedPlatform ? [selectedPlatform] : ALL_PLATFORMS

    addLog(`开始${fullSync ? '全量' : '增量'}同步 ${platforms.length} 个平台...`)

    const results: SyncResult[] = []
    for (const p of platforms) {
      const meta = PLATFORM_META[p]
      addLog(`正在同步 ${meta?.name ?? p}...`)
      try {
        await syncPlatform(p, fullSync)
        // Since backend returns only a message (async), we simulate a result
        const mockResult: SyncResult = { platform: p, success: true, added: 0, skipped: 0, errors: 0 }
        results.push(mockResult)
        addLog(`✓ ${meta?.name ?? p} 同步已启动`)
      } catch (err: any) {
        const mockResult: SyncResult = {
          platform: p, success: false, added: 0, skipped: 0, errors: 1,
          error_msg: err?.message ?? '未知错误',
        }
        results.push(mockResult)
        addLog(`✗ ${meta?.name ?? p} 同步失败`)
      }
    }

    setResults(results)
    setSyncing(false)
    push('同步任务已触发，后端正在处理', 'success')
    addLog('同步任务已全部触发，后端异步处理中...')
  }

  function addLog(msg: string) {
    const ts = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    setLiveLog(prev => [...prev, `[${ts}] ${msg}`])
  }

  async function handleResync() {
    if (syncing) return
    setShowResyncConfirm(false)
    setSyncing(true)
    setLiveLog([])
    setResults([])

    const platforms = selectedPlatform ? [selectedPlatform] : ALL_PLATFORMS

    addLog(`开始重新同步 ${platforms.length} 个平台（先删除后全量同步）...`)

    const results: SyncResult[] = []
    for (const p of platforms) {
      const meta = PLATFORM_META[p]
      addLog(`正在重新同步 ${meta?.name ?? p}...`)
      try {
        await resyncPlatform(p)
        const mockResult: SyncResult = { platform: p, success: true, added: 0, skipped: 0, errors: 0 }
        results.push(mockResult)
        addLog(`✓ ${meta?.name ?? p} 重新同步已启动`)
      } catch (err: any) {
        const mockResult: SyncResult = {
          platform: p, success: false, added: 0, skipped: 0, errors: 1,
          error_msg: err?.message ?? '未知错误',
        }
        results.push(mockResult)
        addLog(`✗ ${meta?.name ?? p} 重新同步失败`)
      }
    }

    setResults(results)
    setSyncing(false)
    push('重新同步任务已触发，后端正在处理', 'success')
    addLog('重新同步任务已全部触发，后端异步处理中...')
  }

  return (
    <div className="flex flex-col h-full">
      {/* Topbar */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-ink-100 bg-white/80 backdrop-blur-sm flex-shrink-0">
        <div>
          <h1 className="font-display font-semibold text-ink-800">同步状态</h1>
          <p className="text-xs text-ink-400 mt-0.5">拉取各平台最新收藏</p>
        </div>
        <div className="flex items-center gap-2">
          {syncing && (
            <div className="flex items-center gap-1.5 text-xs text-accent">
              <Loader2 size={12} className="animate-spin" />
              同步中...
            </div>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5 scrollbar-none">
        {/* Control panel */}
        <div className="card p-4 space-y-4">
          <h2 className="text-sm font-semibold text-ink-700">同步控制</h2>

          {/* Platform selector */}
          <div>
            <p className="text-xs text-ink-400 mb-2">选择平台</p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setSelectedPlatform('')}
                className={cx(
                  'text-xs px-3 py-1.5 rounded-lg border transition-all',
                  !selectedPlatform ? 'bg-accent text-white border-accent' : 'border-ink-200 text-ink-600 hover:border-ink-300'
                )}
              >
                全部平台
              </button>
              {ALL_PLATFORMS.map(id => (
                <button
                  key={id}
                  onClick={() => setSelectedPlatform(selectedPlatform === id ? '' : id)}
                  className={cx(
                    'text-xs px-3 py-1.5 rounded-lg border transition-all',
                    selectedPlatform === id ? 'bg-accent text-white border-accent' : 'border-ink-200 text-ink-600 hover:border-ink-300'
                  )}
                >
                  {PLATFORM_META[id]?.name ?? id}
                </button>
              ))}
            </div>
          </div>

          {/* Time range filter */}
          <div className="border-t border-ink-100 pt-4">
            <p className="text-xs text-ink-400 mb-2">时间范围</p>
            <div className="flex flex-wrap gap-1.5">
              {TIME_RANGES.map(range => (
                <button
                  key={range.value}
                  onClick={() => setTimeRange(range.value)}
                  className={cx(
                    'text-xs px-2.5 py-1.5 rounded-lg border transition-all',
                    timeRange === range.value
                      ? 'bg-accent text-white border-accent'
                      : 'border-ink-200 text-ink-600 hover:border-ink-300'
                  )}
                >
                  {range.label}
                </button>
              ))}
            </div>
          </div>

          {/* Existing memories - accordion for all platforms, dropdown for single platform */}
          <div className="border-t border-ink-100 pt-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-ink-400 flex items-center gap-1.5">
                <FolderOpen size={12} />
                已有收藏
                {!selectedPlatform && ` (${Object.values(platformMemoriesMap).flat().length} total)`}
              </p>
              {(selectedPlatform ? platformMemories.length > 0 : Object.keys(platformMemoriesMap).length > 0) && (
                <button
                  onClick={selectAllMemories}
                  className="text-xs text-accent hover:text-accent/80"
                >
                  {selectedMemoryIds.size === (selectedPlatform ? platformMemories.length : Object.values(platformMemoriesMap).flat().length) ? '取消全选' : '全选'}
                </button>
              )}
            </div>

            {loadingMemories ? (
              <div className="flex items-center gap-2 text-xs text-ink-400 py-2">
                <Loader2 size={12} className="animate-spin" />
                加载中...
              </div>
            ) : !selectedPlatform ? (
              // Accordion for all platforms
              Object.keys(platformMemoriesMap).length === 0 ? (
                <p className="text-xs text-ink-400 py-2">暂无收藏记录</p>
              ) : (
                <div className="space-y-2">
                  {ALL_PLATFORMS.map(platformId => {
                    const memories = platformMemoriesMap[platformId] || []
                    if (memories.length === 0) return null
                    const isExpanded = expandedPlatforms.has(platformId)

                    return (
                      <div key={platformId} className="border border-ink-200 rounded-lg overflow-hidden">
                        <button
                          onClick={() => togglePlatformExpand(platformId)}
                          className="w-full flex items-center justify-between px-3 py-2 bg-ink-50 hover:bg-ink-100 transition-colors"
                        >
                          <span className="flex items-center gap-2">
                            <span className={cx('text-xs transition-transform', isExpanded ? 'rotate-90' : '')}>
                              <ChevronRight size={12} />
                            </span>
                            <span className="text-sm font-medium text-ink-700">
                              {PLATFORM_META[platformId]?.name ?? platformId}
                            </span>
                            <span className="text-xs text-ink-400">({memories.length})</span>
                          </span>
                        </button>
                        {isExpanded && (
                          <div className="max-h-48 overflow-y-auto border-t border-ink-200">
                            {memories.map(memory => (
                              <label
                                key={memory.memory_id}
                                className="flex items-start gap-2 px-3 py-2 hover:bg-ink-50 cursor-pointer border-b border-ink-100 last:border-0"
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedMemoryIds.has(memory.memory_id || '')}
                                  onChange={() => toggleMemorySelection(memory.memory_id || '')}
                                  className="mt-0.5 rounded border-ink-300 text-accent focus:ring-accent"
                                />
                                <div className="flex-1 min-w-0">
                                  <p className="text-xs text-ink-700 truncate">{memory.title}</p>
                                  <p className="text-xs text-ink-400 truncate">
                                    {new Date(memory.bookmarked_at).toLocaleDateString('zh-CN')}
                                  </p>
                                </div>
                              </label>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )
            ) : platformMemories.length === 0 ? (
              <p className="text-xs text-ink-400 py-2">暂无收藏记录</p>
            ) : (
              // Dropdown for single platform
              <div className="relative">
                <button
                  onClick={() => setShowMemoriesDropdown(v => !v)}
                  className="w-full flex items-center justify-between px-3 py-2 rounded-lg border border-ink-200 text-sm hover:border-ink-300 transition-colors"
                >
                  <span className="truncate text-ink-700">
                    {selectedMemoryIds.size === 0
                      ? '点击选择要同步的内容...'
                      : `已选择 ${selectedMemoryIds.size} 项`}
                  </span>
                  <ChevronDown size={14} className={cx('text-ink-400 transition-transform', showMemoriesDropdown && 'rotate-180')} />
                </button>

                {showMemoriesDropdown && (
                  <div className="absolute z-10 mt-1 w-full max-h-60 overflow-y-auto bg-white border border-ink-200 rounded-lg shadow-lg">
                    {platformMemories.map(memory => (
                      <label
                        key={memory.memory_id}
                        className="flex items-start gap-2 px-3 py-2 hover:bg-ink-50 cursor-pointer border-b border-ink-100 last:border-0"
                      >
                        <input
                          type="checkbox"
                          checked={selectedMemoryIds.has(memory.memory_id || '')}
                          onChange={() => toggleMemorySelection(memory.memory_id || '')}
                          className="mt-0.5 rounded border-ink-300 text-accent focus:ring-accent"
                        />
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-ink-700 truncate">{memory.title}</p>
                          <p className="text-xs text-ink-400 truncate">
                            {new Date(memory.bookmarked_at).toLocaleDateString('zh-CN')}
                          </p>
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}

            <p className="text-xs text-ink-400 mt-2">
              选择特定内容后将仅同步所选项目，不选择则同步全部新内容
            </p>
          </div>

          {/* Sync mode toggle */}
          <div className="flex items-center justify-between py-2 border-t border-ink-100">
            <div>
              <p className="text-sm font-medium text-ink-700">全量同步</p>
              <p className="text-xs text-ink-400 mt-0.5">重新拉取所有历史数据（首次使用或数据修复时使用）</p>
            </div>
            <button
              onClick={() => setFullSync(v => !v)}
              className={cx(
                'relative w-10 h-6 rounded-full transition-colors duration-200 flex-shrink-0',
                fullSync ? 'bg-accent' : 'bg-ink-200'
              )}
            >
              <span className={cx(
                'absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200',
                fullSync ? 'translate-x-5' : 'translate-x-1'
              )} />
            </button>
          </div>

          {/* Sync button */}
          <button
            onClick={handleSync}
            disabled={syncing}
            className={cx(
              'btn-primary w-full justify-center text-sm py-2.5',
              syncing && 'opacity-70 cursor-not-allowed'
            )}
          >
            {syncing
              ? <><Loader2 size={15} className="animate-spin" />同步中...</>
              : <><Zap size={15} />{fullSync ? '全量' : '增量'}同步{selectedPlatform ? ` · ${PLATFORM_META[selectedPlatform]?.name}` : ' · 全部平台'}</>
            }
          </button>

          {/* Resync button */}
          <div className="pt-2 border-t border-ink-100">
            <button
              onClick={() => setShowResyncConfirm(true)}
              disabled={syncing}
              className={cx(
                'w-full justify-center text-sm py-2.5 rounded-xl border-2 border-dashed border-danger/30 text-danger hover:bg-danger/5 hover:border-danger/50 transition-all flex items-center gap-2',
                syncing && 'opacity-50 cursor-not-allowed'
              )}
            >
              <Trash2 size={15} />
              重新同步{selectedPlatform ? ` · ${PLATFORM_META[selectedPlatform]?.name}` : ' · 全部平台'}
            </button>
            <p className="text-xs text-ink-400 mt-2 text-center">
              先删除现有数据，再执行全量同步（用于数据修复）
            </p>
          </div>
        </div>

        {/* Resync Confirm Modal */}
        {showResyncConfirm && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-2xl p-6 max-w-sm w-full shadow-2xl">
              <div className="flex items-center gap-3 text-danger mb-4">
                <AlertTriangle size={24} />
                <h3 className="font-semibold text-lg">确认重新同步？</h3>
              </div>
              <p className="text-ink-600 text-sm mb-4">
                此操作将<span className="text-danger font-medium">删除</span>
                {selectedPlatform ? ` ${PLATFORM_META[selectedPlatform]?.name} ` : '所有平台 '}
                的现有数据，然后重新全量同步。
              </p>
              <p className="text-ink-400 text-xs mb-6">
                该操作不可恢复，请确保您了解此操作的影响。
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowResyncConfirm(false)}
                  className="flex-1 py-2 px-4 rounded-xl border border-ink-200 text-ink-600 hover:bg-ink-50 transition-colors text-sm"
                >
                  取消
                </button>
                <button
                  onClick={handleResync}
                  className="flex-1 py-2 px-4 rounded-xl bg-danger text-white hover:bg-danger/90 transition-colors text-sm font-medium"
                >
                  确认删除并同步
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Live log */}
        {liveLog.length > 0 && (
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-ink-700 mb-3">同步日志</h2>
            <div className="bg-ink-900 rounded-lg p-3 font-mono text-xs space-y-1 max-h-48 overflow-y-auto scrollbar-none">
              {liveLog.map((line, i) => (
                <p key={i} className={cx(
                  'leading-relaxed',
                  line.includes('✓') ? 'text-success' : line.includes('✗') ? 'text-danger' : 'text-ink-300'
                )}>
                  {line}
                </p>
              ))}
            </div>
          </div>
        )}

        {/* Results */}
        {lastResults.length > 0 && (
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-ink-700 mb-3">本次结果</h2>
            <div className="space-y-2">
              {lastResults.map(r => {
                const meta = PLATFORM_META[r.platform]
                return (
                  <div key={r.platform} className={cx(
                    'flex items-center gap-3 p-3 rounded-xl border text-sm',
                    r.success ? 'bg-green-50 border-green-100' : 'bg-red-50 border-red-100'
                  )}>
                    {r.success
                      ? <CheckCircle size={15} className="text-success flex-shrink-0" />
                      : <XCircle size={15} className="text-danger flex-shrink-0" />
                    }
                    <span className="font-medium text-ink-800 flex-1">{meta?.name ?? r.platform}</span>
                    {r.success ? (
                      <div className="flex gap-3 text-xs text-ink-500">
                        <span className="text-success font-medium">+{r.added} 新增</span>
                        {r.skipped > 0 && (
                          <span className="flex items-center gap-1">
                            <SkipForward size={11} />{r.skipped} 跳过
                          </span>
                        )}
                        {r.errors > 0 && <span className="text-danger">{r.errors} 失败</span>}
                      </div>
                    ) : (
                      <span className="text-xs text-danger truncate max-w-[160px]">{r.error_msg}</span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Info */}
        <div className="p-4 rounded-xl bg-ink-50 border border-ink-100 text-xs text-ink-500 leading-relaxed">
          <p className="font-medium text-ink-700 mb-1">自动同步</p>
          <p>系统默认每 6 小时自动触发一次增量同步，可在设置页调整间隔。首次接入某平台后建议执行一次全量同步。</p>
        </div>
      </div>
    </div>
  )
}
