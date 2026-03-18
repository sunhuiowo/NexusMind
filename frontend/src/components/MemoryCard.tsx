// components/MemoryCard.tsx
import { ExternalLink, Star, Trash2 } from 'lucide-react'
import type { MemoryCard as IMemoryCard } from '../api/types'
import { cx, formatDate, importanceClass, MEDIA_LABELS, MEDIA_COLORS, PLATFORM_META } from '../utils'
import { deleteMemory, markImportant } from '../api/apiClient'
import { useToastStore } from '../store'

interface Props {
  card: IMemoryCard
  onDelete?: (id: string) => void
  compact?: boolean
}

export default function MemoryCard({ card, onDelete, compact = false }: Props) {
  const push = useToastStore((s) => s.push)
  const platform = PLATFORM_META[card.platform_name?.toLowerCase()] ?? {
    name: card.platform_name,
    color: 'bg-ink-100 text-ink-600',
    emoji: '◎',
  }
  const mediaColor = MEDIA_COLORS[card.media_type ?? 'text'] ?? 'bg-ink-100 text-ink-600'
  const mediaLabel = MEDIA_LABELS[card.media_type ?? 'text'] ?? card.media_type

  async function handleMarkImportant() {
    if (!card.memory_id) return
    try {
      await markImportant(card.memory_id)
      push('已标记为重要', 'success')
    } catch {
      push('操作失败', 'error')
    }
  }

  async function handleDelete() {
    if (!card.memory_id) return
    try {
      await deleteMemory(card.memory_id)
      push('已删除', 'info')
      onDelete?.(card.memory_id)
    } catch {
      push('删除失败', 'error')
    }
  }

  return (
    <div className="card p-4 hover:shadow-md transition-all duration-200 group animate-fade-in">
      {/* Header row */}
      <div className="flex items-start gap-3">
        {/* Thumbnail or media icon */}
        {card.thumbnail_url && !compact ? (
          <img
            src={card.thumbnail_url}
            alt=""
            className="w-14 h-10 object-cover rounded-md flex-shrink-0 bg-ink-100"
            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
          />
        ) : (
          <div className={cx('media-icon text-xs font-bold', mediaColor)}>
            {mediaLabel?.slice(0, 2) ?? '??'}
          </div>
        )}

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            {/* Platform badge */}
            <span className={cx('inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-md border', platform.color)}>
              <span className="text-[10px]">{platform.emoji}</span>
              {platform.name}
            </span>
            {/* Media type */}
            <span className={cx('text-[11px] px-1.5 py-0.5 rounded font-medium', mediaColor)}>
              {mediaLabel}
            </span>
            {/* Importance dot */}
            {card.importance !== undefined && (
              <span className={cx('imp-ring', importanceClass(card.importance))} title={`重要性 ${(card.importance * 100).toFixed(0)}%`} />
            )}
            {/* Date */}
            <span className="text-[11px] text-ink-400 ml-auto flex-shrink-0">
              {formatDate(card.bookmarked_at)}
            </span>
          </div>

          {/* Title */}
          <h3 className="text-sm font-semibold text-ink-800 line-clamp-2 leading-snug mb-1">
            {card.title || '无标题'}
          </h3>

          {/* Author */}
          {card.author && (
            <p className="text-[11px] text-ink-400 mb-1.5">by {card.author}</p>
          )}

          {/* Summary */}
          {!compact && card.summary && (
            <p className="text-xs text-ink-500 line-clamp-3 leading-relaxed mb-2">
              {card.summary}
            </p>
          )}

          {/* Tags */}
          {card.tags && card.tags.length > 0 && !compact && (
            <div className="flex flex-wrap gap-1 mb-2">
              {card.tags.slice(0, 5).map((tag) => (
                <span key={tag} className="tag">{tag}</span>
              ))}
            </div>
          )}

          {/* Footer actions */}
          <div className="flex items-center gap-2 mt-1">
            <a
              href={card.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-dark transition-colors font-medium truncate max-w-[200px]"
            >
              <ExternalLink size={11} />
              查看原文
            </a>

            {/* Relevance score */}
            {card.relevance_score !== undefined && card.relevance_score > 0 && (
              <span className="text-[10px] text-ink-300 font-mono ml-auto">
                {(card.relevance_score * 100).toFixed(0)}%
              </span>
            )}

            {/* Action buttons (show on hover) */}
            {card.memory_id && (
              <div className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={handleMarkImportant}
                  className="p-1 rounded text-ink-400 hover:text-warning hover:bg-amber-50 transition-colors"
                  title="标记为重要"
                >
                  <Star size={13} />
                </button>
                <button
                  onClick={handleDelete}
                  className="p-1 rounded text-ink-400 hover:text-danger hover:bg-red-50 transition-colors"
                  title="删除"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
