// pages/Library.tsx — v1.2.0  真实 /memories 接口 + 分页 + 标签过滤
import { useState, useEffect, useCallback, useRef } from 'react'
import { Search, SlidersHorizontal, X, Library as LibraryIcon, Tag, RefreshCw } from 'lucide-react'
import type { MemoryCard as IMemoryCard } from '../api/types'
import { listMemories, getStats, searchByTags } from '../api/apiClient'
import { useStatsStore, useToastStore } from '../store'
import MemoryCard from '../components/MemoryCard'
import { cx, PLATFORM_META, MEDIA_LABELS } from '../utils'

const PLATFORMS = Object.entries(PLATFORM_META).map(([id, meta]) => ({ id, ...meta }))
const MEDIA_TYPES = Object.entries(MEDIA_LABELS).map(([id, label]) => ({ id, label }))
const TIME_RANGES = [
  { label: '全部', days: 0 }, { label: '今天', days: 1 },
  { label: '本周', days: 7 }, { label: '本月', days: 30 }, { label: '三个月', days: 90 },
]
const PAGE_SIZE = 20

export default function Library() {
  const [cards, setCards] = useState<IMemoryCard[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [platform, setPlatform] = useState('')
  const [mediaType, setMediaType] = useState('')
  const [timeDays, setTimeDays] = useState(0)
  const [tagInput, setTagInput] = useState('')
  const [activeTags, setActiveTags] = useState<string[]>([])
  const [orderBy, setOrderBy] = useState<'bookmarked_at' | 'importance'>('bookmarked_at')
  const [loading, setLoading] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const setStats = useStatsStore(s => s.setStats)
  const push = useToastStore(s => s.push)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setDebouncedQuery(query), 400)
    return () => clearTimeout(debounceRef.current)
  }, [query])

  const loadPage = useCallback(async (pg: number, reset = false) => {
    setLoading(true)
    try {
      let result
      if (activeTags.length > 0 && !debouncedQuery) {
        const tagResult = await searchByTags(activeTags)
        const sliced = tagResult.hits.slice((pg-1)*PAGE_SIZE, pg*PAGE_SIZE)
        result = { items: sliced, total: tagResult.hits.length, page: pg, page_size: PAGE_SIZE, has_more: pg*PAGE_SIZE < tagResult.hits.length }
      } else {
        result = await listMemories({
          platform: platform || undefined, media_type: mediaType || undefined,
          days: timeDays || undefined,
          tags: activeTags.length > 0 ? activeTags.join(',') : undefined,
          query: debouncedQuery || undefined, page: pg, page_size: PAGE_SIZE, order_by: orderBy,
        })
      }
      setTotal(result.total); setHasMore(result.has_more)
      setCards(reset ? result.items : prev => [...prev, ...result.items])
    } catch { push('加载失败', 'error') }
    finally { setLoading(false) }
  }, [platform, mediaType, timeDays, debouncedQuery, activeTags, orderBy, push])

  useEffect(() => {
    setPage(1); setCards([])
    loadPage(1, true)
    getStats().then(setStats).catch(() => {})
  }, [platform, mediaType, timeDays, debouncedQuery, activeTags, orderBy])

  function loadMore() { const n = page + 1; setPage(n); loadPage(n, false) }
  function handleDelete(id: string) { setCards(prev => prev.filter(c => c.memory_id !== id)); setTotal(t => t - 1) }
  function addTag() { const t = tagInput.trim(); if (t && !activeTags.includes(t)) setActiveTags(p => [...p, t]); setTagInput('') }
  function removeTag(tag: string) { setActiveTags(p => p.filter(t => t !== tag)) }

  const activeFilterCount = [platform, mediaType, timeDays > 0, activeTags.length > 0].filter(Boolean).length

  return (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-4 border-b border-ink-100 bg-white/80 backdrop-blur-sm flex-shrink-0">
        <div>
          <h1 className="font-display font-semibold text-ink-800">记忆库</h1>
          <p className="text-xs text-ink-400 mt-0.5">共 {total.toLocaleString()} 条记忆</p>
        </div>
        <div className="flex items-center gap-2">
          <select value={orderBy} onChange={e => setOrderBy(e.target.value as typeof orderBy)}
            className="text-xs border border-ink-200 rounded-lg px-2 py-1.5 text-ink-600 bg-white focus:outline-none focus:border-accent/40">
            <option value="bookmarked_at">最新收藏</option>
            <option value="importance">最重要</option>
          </select>
          <button onClick={() => setShowFilters(v => !v)}
            className={cx('btn-outline text-xs gap-1.5 relative', showFilters && 'border-accent/40 text-accent')}>
            <SlidersHorizontal size={13} />筛选
            {activeFilterCount > 0 && (
              <span className="absolute -top-1.5 -right-1.5 w-4 h-4 bg-accent text-white text-[9px] rounded-full flex items-center justify-center font-bold">{activeFilterCount}</span>
            )}
          </button>
        </div>
      </header>

      <div className="px-6 pt-4 pb-2 bg-white border-b border-ink-100 flex-shrink-0">
        <div className="relative mb-3">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input className="input-base pl-9 pr-9 text-sm" placeholder="语义搜索记忆库..."
            value={query} onChange={e => setQuery(e.target.value)} />
          {query && <button onClick={() => setQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-600"><X size={14} /></button>}
        </div>

        {showFilters && (
          <div className="space-y-3 pb-3 animate-slide-up">
            <div>
              <p className="text-[11px] text-ink-400 font-medium mb-1.5">时间范围</p>
              <div className="flex flex-wrap gap-1.5">
                {TIME_RANGES.map(({ label, days }) => (
                  <button key={days} onClick={() => setTimeDays(days)}
                    className={cx('text-xs px-3 py-1 rounded-lg border transition-all',
                      timeDays === days ? 'bg-accent text-white border-accent' : 'border-ink-200 text-ink-600 hover:border-ink-300')}>{label}</button>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[11px] text-ink-400 font-medium mb-1.5">平台</p>
              <div className="flex flex-wrap gap-1.5">
                <button onClick={() => setPlatform('')}
                  className={cx('text-xs px-3 py-1 rounded-lg border transition-all', !platform ? 'bg-accent text-white border-accent' : 'border-ink-200 text-ink-600 hover:border-ink-300')}>全部</button>
                {PLATFORMS.map(({ id, name }) => (
                  <button key={id} onClick={() => setPlatform(platform === id ? '' : id)}
                    className={cx('text-xs px-3 py-1 rounded-lg border transition-all',
                      platform === id ? 'bg-accent text-white border-accent' : 'border-ink-200 text-ink-600 hover:border-ink-300')}>{name}</button>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[11px] text-ink-400 font-medium mb-1.5">类型</p>
              <div className="flex flex-wrap gap-1.5">
                <button onClick={() => setMediaType('')}
                  className={cx('text-xs px-3 py-1 rounded-lg border transition-all', !mediaType ? 'bg-accent text-white border-accent' : 'border-ink-200 text-ink-600 hover:border-ink-300')}>全部</button>
                {MEDIA_TYPES.map(({ id, label }) => (
                  <button key={id} onClick={() => setMediaType(mediaType === id ? '' : id)}
                    className={cx('text-xs px-3 py-1 rounded-lg border transition-all',
                      mediaType === id ? 'bg-accent text-white border-accent' : 'border-ink-200 text-ink-600 hover:border-ink-300')}>{label}</button>
                ))}
              </div>
            </div>
            <div>
              <p className="text-[11px] text-ink-400 font-medium mb-1.5">标签过滤</p>
              <div className="flex gap-2 mb-2">
                <input className="input-base text-xs flex-1" placeholder="输入标签后按 Enter"
                  value={tagInput} onChange={e => setTagInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addTag()} />
                <button onClick={addTag} className="btn-outline text-xs px-3"><Tag size={12} /></button>
              </div>
              {activeTags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {activeTags.map(tag => (
                    <span key={tag} className="inline-flex items-center gap-1 text-xs bg-accent/10 text-accent px-2 py-0.5 rounded-md border border-accent/20">
                      {tag}<button onClick={() => removeTag(tag)}><X size={10} /></button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-2.5 scrollbar-none">
        {loading && cards.length === 0 ? (
          <div className="space-y-2.5">
            {[1,2,3,4].map(i => (
              <div key={i} className="card p-4 animate-pulse">
                <div className="flex gap-3">
                  <div className="w-9 h-9 bg-ink-100 rounded-lg flex-shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3 bg-ink-100 rounded w-1/3" /><div className="h-4 bg-ink-100 rounded w-3/4" /><div className="h-3 bg-ink-100 rounded" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : cards.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <LibraryIcon size={28} className="text-ink-300 mb-3" />
            <p className="text-sm text-ink-500 font-medium">没有找到记忆</p>
            <p className="text-xs text-ink-400 mt-1">调整筛选条件，或先在同步页同步平台数据</p>
          </div>
        ) : (
          <>
            {cards.map((card, i) => <MemoryCard key={card.memory_id ?? i} card={card} onDelete={handleDelete} />)}
            {hasMore && (
              <div className="pt-2 pb-6 flex justify-center">
                <button onClick={loadMore} disabled={loading} className="btn-outline text-xs gap-2">
                  {loading ? <RefreshCw size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                  加载更多（还有 {total - cards.length} 条）
                </button>
              </div>
            )}
            {!hasMore && cards.length > 0 && (
              <p className="text-center text-xs text-ink-300 py-4">已加载全部 {cards.length} 条</p>
            )}
          </>
        )}
      </div>
    </div>
  )
}
