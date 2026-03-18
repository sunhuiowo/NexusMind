// components/ChatInput.tsx
import { useState, useRef, useCallback } from 'react'
import { Send, Mic, MicOff, Loader2 } from 'lucide-react'
import { cx } from '../utils'

const SUGGESTIONS = [
  '我最近收藏了哪些关于 AI 的内容？',
  '总结我 GitHub Star 的 Python 项目',
  '最近7天有什么新收藏？',
  '把我在 YouTube 和 B 站的视频按主题分类',
]

interface Props {
  onSubmit: (query: string) => void
  loading?: boolean
  disabled?: boolean
}

export default function ChatInput({ onSubmit, loading, disabled }: Props) {
  const [value, setValue] = useState('')
  const [listening, setListening] = useState(false)
  const [showSuggestions, setShowSuggestions] = useState(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  const submit = useCallback(() => {
    const q = value.trim()
    if (!q || loading || disabled) return
    onSubmit(q)
    setValue('')
    setShowSuggestions(false)
  }, [value, loading, disabled, onSubmit])

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function toggleVoice() {
    const SR = window.SpeechRecognition ?? (window as any).webkitSpeechRecognition
    if (!SR) return alert('浏览器不支持语音识别')

    if (listening) {
      recognitionRef.current?.stop()
      setListening(false)
      return
    }

    const rec = new SR()
    rec.lang = 'zh-CN'
    rec.continuous = false
    rec.interimResults = false
    rec.onresult = (e: SpeechRecognitionEvent) => {
      const transcript = e.results[0][0].transcript
      setValue(transcript)
      setListening(false)
    }
    rec.onerror = () => setListening(false)
    rec.onend = () => setListening(false)
    rec.start()
    recognitionRef.current = rec
    setListening(true)
  }

  return (
    <div className="space-y-3">
      {/* Suggestion pills */}
      {showSuggestions && value === '' && (
        <div className="flex flex-wrap gap-2 animate-fade-in">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => { setValue(s); inputRef.current?.focus() }}
              className="text-xs px-3 py-1.5 rounded-full border border-ink-200 text-ink-500
                         hover:border-accent/40 hover:text-accent hover:bg-accent/5 transition-all"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input row */}
      <div className={cx(
        'flex items-end gap-2 p-2 rounded-2xl border bg-white shadow-sm transition-all duration-200',
        'focus-within:border-accent/40 focus-within:shadow-md focus-within:shadow-accent/10',
        disabled ? 'opacity-60 pointer-events-none' : 'border-ink-200'
      )}>
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKey}
          onFocus={() => setShowSuggestions(true)}
          placeholder="问问你的记忆库... （Enter 发送，Shift+Enter 换行）"
          rows={1}
          className="flex-1 resize-none bg-transparent text-sm text-ink-800 placeholder-ink-400
                     outline-none px-2 py-1.5 leading-relaxed min-h-[36px] max-h-[120px]
                     scrollbar-none"
          style={{ height: 'auto' }}
          onInput={(e) => {
            const el = e.currentTarget
            el.style.height = 'auto'
            el.style.height = Math.min(el.scrollHeight, 120) + 'px'
          }}
        />

        {/* Voice btn */}
        <button
          type="button"
          onClick={toggleVoice}
          className={cx(
            'p-2 rounded-xl transition-all duration-150',
            listening
              ? 'bg-danger text-white animate-pulse-soft'
              : 'text-ink-400 hover:text-ink-600 hover:bg-ink-100'
          )}
          title={listening ? '停止录音' : '语音输入'}
        >
          {listening ? <MicOff size={16} /> : <Mic size={16} />}
        </button>

        {/* Send btn */}
        <button
          type="button"
          onClick={submit}
          disabled={!value.trim() || loading || disabled}
          className={cx(
            'p-2 rounded-xl transition-all duration-150',
            value.trim() && !loading && !disabled
              ? 'bg-accent text-white hover:bg-accent-dark active:scale-95 shadow-sm shadow-accent/30'
              : 'text-ink-300 bg-ink-100 cursor-not-allowed'
          )}
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  )
}
