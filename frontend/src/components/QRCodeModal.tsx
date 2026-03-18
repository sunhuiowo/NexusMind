// components/QRCodeModal.tsx — v1.2.1
// 二维码完全在前端用 JS 生成，后端只需返回 qrcode_url
// 消除 Python qrcode 库依赖问题

import { useState, useEffect, useRef } from 'react'
import { X, CheckCircle, RefreshCw, Clock, Loader2 } from 'lucide-react'
import QRCode from 'qrcode'
import { getQRCode, pollQRCode } from '../api/apiClient'
import { usePlatformStore, useToastStore } from '../store'
import { cx, PLATFORM_META } from '../utils'

interface Props {
  platform: string
  onClose: () => void
  onSuccess: () => void
}

type ScanStatus = 'loading' | 'ready' | 'scanned' | 'confirmed' | 'expired' | 'error'

export default function QRCodeModal({ platform, onClose, onSuccess }: Props) {
  const [scanStatus, setScanStatus] = useState<ScanStatus>('loading')
  const [qrcodeKey, setQrcodeKey] = useState('')
  const [qrcodeUrl, setQrcodeUrl] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [errorMsg, setErrorMsg] = useState('')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval>>()
  const countdownRef = useRef<ReturnType<typeof setInterval>>()
  const updateStatus = usePlatformStore(s => s.updateStatus)
  const push = useToastStore(s => s.push)
  const meta = PLATFORM_META[platform]

  // Render QR code to canvas using qrcode.js
  async function renderQR(url: string) {
    if (!canvasRef.current || !url) return
    try {
      await QRCode.toCanvas(canvasRef.current, url, {
        width: 180,
        margin: 2,
        color: { dark: '#1e1d1a', light: '#ffffff' },
        errorCorrectionLevel: 'M',
      })
    } catch (e) {
      console.error('[QRCode] render failed:', e)
      // Fallback: try with canvas element
      try {
        const dataUrl = await QRCode.toDataURL(url, { width: 180, margin: 2 })
        const img = new Image()
        img.src = dataUrl
        img.onload = () => {
          const ctx = canvasRef.current?.getContext('2d')
          if (ctx) ctx.drawImage(img, 0, 0)
        }
      } catch (e2) {
        console.error('[QRCode] fallback also failed:', e2)
      }
    }
  }

  async function loadQRCode() {
    setScanStatus('loading')
    setErrorMsg('')
    clearInterval(pollRef.current)
    clearInterval(countdownRef.current)

    try {
      const result = await getQRCode(platform)

      if (result.error) {
        setScanStatus('error')
        setErrorMsg(result.error)
        return
      }

      setQrcodeKey(result.qrcode_key)
      setQrcodeUrl(result.qrcode_url)
      setCountdown(result.expires_in || 180)
      setScanStatus('ready')

      // Render QR after state update
      setTimeout(() => renderQR(result.qrcode_url), 50)

      // Start polling
      pollRef.current = setInterval(async () => {
        try {
          const poll = await pollQRCode(platform, result.qrcode_key)
          if (poll.status === 'scanned') {
            setScanStatus('scanned')
          } else if (poll.status === 'confirmed') {
            setScanStatus('confirmed')
            clearInterval(pollRef.current)
            clearInterval(countdownRef.current)
            updateStatus(platform, { status: 'connected' })
            push(`${meta?.name ?? platform} 扫码登录成功！`, 'success')
            setTimeout(() => { onSuccess(); onClose() }, 1500)
          } else if (poll.status === 'expired') {
            setScanStatus('expired')
            clearInterval(pollRef.current)
            clearInterval(countdownRef.current)
          }
        } catch { /* silently ignore poll errors */ }
      }, 2000)

      // Countdown timer
      countdownRef.current = setInterval(() => {
        setCountdown(v => {
          if (v <= 1) {
            clearInterval(countdownRef.current)
            setScanStatus(s => (s === 'ready' || s === 'scanned') ? 'expired' : s)
            return 0
          }
          return v - 1
        })
      }, 1000)

    } catch (e: any) {
      setScanStatus('error')
      setErrorMsg(e?.response?.data?.detail ?? '网络错误，请检查后端服务')
    }
  }

  useEffect(() => {
    loadQRCode()
    return () => {
      clearInterval(pollRef.current)
      clearInterval(countdownRef.current)
    }
  }, [platform])

  // Re-render QR when URL changes and status is ready
  useEffect(() => {
    if (scanStatus === 'ready' && qrcodeUrl) {
      renderQR(qrcodeUrl)
    }
  }, [scanStatus, qrcodeUrl])

  const statusText: Record<ScanStatus, string> = {
    loading:   '正在获取二维码...',
    ready:     `请用 ${meta?.name ?? platform} App 扫描`,
    scanned:   '已扫码，请在手机上确认登录',
    confirmed: '登录成功！',
    expired:   '二维码已过期，请重新获取',
    error:     errorMsg || '获取失败，请重试',
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className="bg-white rounded-2xl shadow-2xl p-6 w-[300px] relative animate-slide-up">
        {/* Close */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-ink-400 hover:text-ink-700 transition-colors"
        >
          <X size={18} />
        </button>

        {/* Header */}
        <div className="flex items-center gap-2.5 mb-5">
          <div className={cx(
            'w-9 h-9 rounded-xl flex items-center justify-center text-base font-bold border',
            meta?.color ?? 'bg-ink-100 text-ink-600'
          )}>
            {meta?.emoji ?? '◎'}
          </div>
          <div>
            <p className="text-sm font-semibold text-ink-800">{meta?.name ?? platform}</p>
            <p className="text-xs text-ink-400">扫码登录</p>
          </div>
        </div>

        {/* QR Area */}
        <div className="flex flex-col items-center">
          <div className="relative w-[180px] h-[180px] rounded-2xl overflow-hidden border border-ink-100 bg-white flex items-center justify-center">
            {/* Canvas always mounted, hidden when not ready */}
            <canvas
              ref={canvasRef}
              className={cx(
                'rounded-xl transition-opacity duration-300',
                (scanStatus === 'ready' || scanStatus === 'scanned') ? 'opacity-100' : 'opacity-0 absolute'
              )}
            />

            {/* Loading overlay */}
            {scanStatus === 'loading' && (
              <div className="absolute inset-0 bg-ink-50 flex items-center justify-center rounded-2xl">
                <Loader2 size={28} className="text-ink-400 animate-spin" />
              </div>
            )}

            {/* Scanned overlay */}
            {scanStatus === 'scanned' && (
              <div className="absolute inset-0 bg-white/85 rounded-2xl flex flex-col items-center justify-center">
                <CheckCircle size={36} className="text-success mb-2" />
                <p className="text-xs text-success font-semibold">已扫码</p>
                <p className="text-[11px] text-ink-400 mt-1">请在手机上确认</p>
              </div>
            )}

            {/* Confirmed overlay */}
            {scanStatus === 'confirmed' && (
              <div className="absolute inset-0 bg-green-50 rounded-2xl flex flex-col items-center justify-center">
                <CheckCircle size={40} className="text-success mb-2" />
                <p className="text-sm text-success font-semibold">登录成功！</p>
              </div>
            )}

            {/* Expired / Error overlay */}
            {(scanStatus === 'expired' || scanStatus === 'error') && (
              <div className="absolute inset-0 bg-ink-50 rounded-2xl flex flex-col items-center justify-center gap-2 p-4">
                <Clock size={28} className="text-ink-400" />
                <p className="text-xs text-ink-500 text-center leading-relaxed">
                  {scanStatus === 'expired' ? '二维码已过期' : errorMsg}
                </p>
                <button
                  onClick={loadQRCode}
                  className="btn-primary text-xs py-1.5 px-3 mt-1"
                >
                  <RefreshCw size={11} />
                  重新获取
                </button>
              </div>
            )}
          </div>

          {/* Status + countdown */}
          <div className="mt-4 text-center">
            <p className={cx(
              'text-xs font-medium',
              scanStatus === 'confirmed' ? 'text-success'
              : scanStatus === 'error' ? 'text-danger'
              : 'text-ink-600'
            )}>
              {statusText[scanStatus]}
            </p>
            {(scanStatus === 'ready' || scanStatus === 'scanned') && countdown > 0 && (
              <p className="text-[10px] text-ink-400 mt-1 tabular-nums">
                二维码 {Math.floor(countdown / 60)}:{String(countdown % 60).padStart(2, '0')} 后过期
              </p>
            )}
          </div>

          {/* Polling indicator */}
          {(scanStatus === 'ready' || scanStatus === 'scanned') && (
            <div className="flex items-center gap-1.5 mt-3">
              <div className="flex gap-0.5">
                {[0, 200, 400].map(delay => (
                  <span
                    key={delay}
                    className="w-1 h-1 bg-ink-300 rounded-full animate-bounce"
                    style={{ animationDelay: `${delay}ms` }}
                  />
                ))}
              </div>
              <span className="text-[10px] text-ink-400">等待扫码</span>
            </div>
          )}
        </div>

        {/* Help text */}
        <p className="text-[10px] text-ink-400 text-center mt-4 leading-relaxed">
          {platform === 'bilibili'
            ? '打开 B站 App → 首页右上角扫一扫'
            : '打开抖音 App → 右上角扫一扫'}
        </p>
      </div>
    </div>
  )
}
