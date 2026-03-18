// ui/Toast.tsx
import { useToastStore } from '../store'
import { CheckCircle, XCircle, Info, AlertTriangle, X } from 'lucide-react'
import { cx } from '../utils'

const ICONS = {
  success: CheckCircle,
  error:   XCircle,
  info:    Info,
  warning: AlertTriangle,
}

const STYLES = {
  success: 'bg-white border-success/30 text-success',
  error:   'bg-white border-danger/30 text-danger',
  info:    'bg-white border-accent/30 text-accent',
  warning: 'bg-white border-warning/30 text-warning',
}

export default function ToastContainer() {
  const { toasts, remove } = useToastStore()

  return (
    <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 items-end pointer-events-none">
      {toasts.map((t) => {
        const Icon = ICONS[t.type]
        return (
          <div
            key={t.id}
            className={cx(
              'pointer-events-auto flex items-center gap-2.5 px-3.5 py-2.5',
              'border rounded-xl shadow-lg text-sm font-medium animate-slide-up',
              STYLES[t.type]
            )}
          >
            <Icon size={14} />
            <span className="text-ink-700">{t.message}</span>
            <button
              onClick={() => remove(t.id)}
              className="ml-1 text-ink-400 hover:text-ink-600 transition-colors"
            >
              <X size={12} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
