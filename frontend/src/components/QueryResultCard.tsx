// components/QueryResultCard.tsx
import { useState, useEffect } from 'react'
import { Sparkles, Clock, Filter, Layers, Search, Network, ChevronDown, ChevronRight, Brain } from 'lucide-react'
import type { QueryResult, QueryIntent } from '../api/types'
import MemoryCard from './MemoryCard'
import { cx, INTENT_LABELS } from '../utils'

interface Props { result: QueryResult; thinking?: string; showThinking?: boolean }

const INTENT_ICONS: Record<QueryIntent, React.ComponentType<{ size?: number; className?: string }>> = {
  search:   Search,
  recent:   Clock,
  summary:  Layers,
  platform: Filter,
  related:  Network,
  complex:  Sparkles,
}

const INTENT_COLORS: Record<QueryIntent, string> = {
  search:   'bg-blue-50 text-blue-600 border-blue-100',
  recent:   'bg-green-50 text-green-600 border-green-100',
  summary:  'bg-purple-50 text-purple-600 border-purple-100',
  platform: 'bg-amber-50 text-amber-700 border-amber-100',
  related:  'bg-teal-50 text-teal-600 border-teal-100',
  complex:  'bg-accent/10 text-accent border-accent/20',
}

export default function QueryResultCard({ result, thinking, showThinking: globalShowThinking = true }: Props) {
  const intent = (result.query_intent ?? 'search') as QueryIntent
  const Icon = INTENT_ICONS[intent] ?? Search
  const colorClass = INTENT_COLORS[intent] ?? INTENT_COLORS.search

  const [showThinking, setShowThinking] = useState(false)

  // Sync with global setting - but still default to collapsed
  useEffect(() => {
    // Global setting controls whether thinking is allowed to show, but still start collapsed
    if (!globalShowThinking) {
      setShowThinking(false)
    }
  }, [globalShowThinking])
  const [showMemories, setShowMemories] = useState(false)

  if (result.total_found === 0) {
    return (
      <div className="text-center py-8 text-ink-400">
        <Search size={28} className="mx-auto mb-2 opacity-30" />
        <p className="text-sm">没有找到相关收藏</p>
        <p className="text-xs mt-1">试试其他关键词，或先同步一下平台</p>
      </div>
    )
  }

  return (
    <div className="animate-slide-up space-y-3">
      {/* Header: intent badge + count + time range */}
      <div className="flex items-center gap-2">
        <span className={cx('inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg border', colorClass)}>
          <Icon size={12} />
          {INTENT_LABELS[intent] ?? intent}
        </span>
        <span className="text-xs text-ink-500">
          找到 <span className="font-semibold text-ink-800">{result.total_found}</span> 条
          {result.time_range && <span className="text-ink-400 ml-1">（{result.time_range}）</span>}
        </span>
      </div>

      {/* 回答 - 直接显示 */}
      {result.overall_summary && (
        <div className="p-3.5 rounded-xl bg-gradient-to-br from-accent/5 to-accent/10 border border-accent/15">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Sparkles size={13} className="text-accent" />
            <span className="text-xs font-semibold text-accent">回答</span>
          </div>
          <p className="text-sm text-ink-700 leading-relaxed">{result.overall_summary}</p>
        </div>
      )}

      {/* 思考过程 - 仅当用户开启时显示 */}
      {thinking && showThinking && (
        <div className="border border-ink-200 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowThinking(!showThinking)}
            className="w-full flex items-center gap-2 px-3 py-2 bg-ink-50 hover:bg-ink-100 transition-colors text-left"
          >
            {showThinking ? <ChevronDown size={14} className="text-ink-500" /> : <ChevronRight size={14} className="text-ink-500" />}
            <Brain size={14} className="text-ink-400" />
            <span className="text-xs font-medium text-ink-600">思考过程</span>
          </button>
          {showThinking && (
            <div className="px-3 py-2.5 border-t border-ink-200 bg-ink-50/50">
              <p className="text-xs text-ink-600 leading-relaxed whitespace-pre-wrap">{thinking}</p>
            </div>
          )}
        </div>
      )}

      {/* 收藏下拉栏 */}
      <div className="border border-ink-200 rounded-lg overflow-hidden">
        <button
          onClick={() => setShowMemories(!showMemories)}
          className="w-full flex items-center justify-between px-3 py-2 bg-white hover:bg-ink-50 transition-colors"
        >
          <span className="flex items-center gap-2">
            {showMemories ? <ChevronDown size={14} className="text-ink-500" /> : <ChevronRight size={14} className="text-ink-500" />}
            <span className="text-xs font-medium text-ink-600">引用收藏</span>
            <span className="text-xs text-ink-400">({result.hits.length})</span>
          </span>
        </button>
        {showMemories && (
          <div className="border-t border-ink-200 max-h-80 overflow-y-auto">
            {result.hits.map((card, i) => (
              <div key={card.memory_id ?? i} className="border-b border-ink-100 last:border-0">
                <MemoryCard card={card} compact />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
