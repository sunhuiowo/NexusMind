// components/PlatformCard.tsx — v1.2.0
// 认证策略：OAuth(YouTube/Twitter/Pocket) | 扫码(Bilibili/抖音) | PAT(GitHub) | Cookie(小红书) | APIKey(微信)
import { useState } from 'react'
import { CheckCircle, AlertCircle, XCircle, Loader2, ExternalLink, Unlink, QrCode, Key, Cookie } from 'lucide-react'
import type { PlatformStatus } from '../api/types'
import { getAuthUrl, revokeAuth, setXhsCookie, setWechatKey, setGithubPAT, setPocketToken } from '../api/apiClient'
import { usePlatformStore, useToastStore } from '../store'
import QRCodeModal from './QRCodeModal'
import { cx, PLATFORM_META } from '../utils'
import { relativeTime } from '../utils'

interface Props { platformId: string; status: PlatformStatus; memCount?: number }

const STATUS_CFG = {
  connected:    { icon: CheckCircle,  color: 'text-success',  label: '已连接',       bg: 'bg-green-50 border-green-100' },
  needs_reauth: { icon: AlertCircle,  color: 'text-warning',  label: '需重新授权',   bg: 'bg-amber-50 border-amber-100' },
  disconnected: { icon: XCircle,      color: 'text-ink-400',  label: '未连接',       bg: 'bg-ink-50 border-ink-200' },
  error:        { icon: AlertCircle,  color: 'text-danger',   label: '连接错误',     bg: 'bg-red-50 border-red-100' },
}

// 每个平台的认证策略
const AUTH_STRATEGY: Record<string, 'oauth' | 'qrcode' | 'pat' | 'cookie' | 'apikey' | 'pocket_oauth'> = {
  youtube: 'oauth', twitter: 'oauth', pocket: 'pocket_oauth',
  bilibili: 'qrcode', douyin: 'qrcode',
  github: 'pat',
  xiaohongshu: 'cookie',
  wechat: 'apikey',
}

const AUTH_HINTS: Record<string, string> = {
  youtube:  '需要 Google OAuth Client ID/Secret（在 Google Cloud Console 创建）',
  twitter:  '需要 Twitter Developer App Client ID/Secret',
  pocket:   '粘贴 Pocket Access Token（从 Pocket 开发者后台获取）',
  bilibili: '使用 B站 App 扫码，无需任何密钥',
  douyin:   '使用抖音 App 扫码，无需任何密钥',
  github:   '在 GitHub 设置 → Developer settings → Personal Access Tokens 创建',
  xiaohongshu: '打开小红书网页版 → F12 → Application → Cookies → 复制全部内容',
  wechat:   '需要企业微信开放 API 权限，在企业微信管理后台获取 API Key',
}

export default function PlatformCard({ platformId, status, memCount }: Props) {
  const meta = PLATFORM_META[platformId] ?? { name: platformId, color: 'bg-ink-100 text-ink-600', emoji: '◎' }
  const cfg = STATUS_CFG[status.status] ?? STATUS_CFG.disconnected
  const StatusIcon = cfg.icon
  const strategy = AUTH_STRATEGY[platformId] ?? 'oauth'
  const updateStatus = usePlatformStore(s => s.updateStatus)
  const push = useToastStore(s => s.push)
  const [busy, setBusy] = useState(false)
  const [showInput, setShowInput] = useState(false)
  const [inputVal, setInputVal] = useState('')
  const [showQR, setShowQR] = useState(false)

  const isConnected = status.status === 'connected'
  const needsReauth = status.status === 'needs_reauth'

  async function handleConnect() {
    if (strategy === 'qrcode') { setShowQR(true); return }
    if (strategy === 'pat' || strategy === 'cookie' || strategy === 'apikey' || strategy === 'pocket_oauth') {
      setShowInput(true); return
    }
    // oauth
    setBusy(true)
    try {
      const { auth_url } = await getAuthUrl(platformId)
      window.open(auth_url, '_blank', 'width=600,height=700')
      push(`已打开 ${meta.name} 授权页，完成后刷新页面`, 'info')
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? '获取授权链接失败'
      if (msg.includes('Client ID') || msg.includes('OAuth')) {
        push(`请先在设置页填入 ${meta.name} Client ID/Secret`, 'warning')
      } else {
        push(msg, 'error')
      }
    } finally { setBusy(false) }
  }

  async function handleSave() {
    const val = inputVal.trim()
    if (!val) return
    setBusy(true)
    try {
      if (strategy === 'pat') {
        await setGithubPAT(val)
      } else if (strategy === 'cookie') {
        await setXhsCookie(val)
      } else if (strategy === 'apikey') {
        await setWechatKey(val)
      } else if (strategy === 'pocket_oauth') {
        await setPocketToken(val)
      }
      updateStatus(platformId, { status: 'connected' })
      push(`${meta.name} 连接成功`, 'success')
      setShowInput(false); setInputVal('')
    } catch { push('保存失败，请检查格式', 'error') }
    finally { setBusy(false) }
  }

  async function handleRevoke() {
    if (!confirm(`确定断开 ${meta.name} 连接？`)) return
    setBusy(true)
    try {
      await revokeAuth(platformId)
      updateStatus(platformId, { status: 'disconnected' })
      push(`已断开 ${meta.name}`, 'info')
    } catch { push('断开失败', 'error') }
    finally { setBusy(false) }
  }

  const inputLabels: Record<string, { label: string; placeholder: string; type: string; icon: React.ReactNode }> = {
    pat:          { label: 'GitHub Personal Access Token', placeholder: 'ghp_...', type: 'password', icon: <Key size={12} /> },
    cookie:       { label: '小红书 Cookie', placeholder: '从浏览器 DevTools 复制全部 Cookie', type: 'text', icon: <Cookie size={12} /> },
    apikey:       { label: '企业微信 API Key', placeholder: 'wx...', type: 'password', icon: <Key size={12} /> },
    pocket_oauth: { label: 'Pocket Access Token', placeholder: '从 Pocket 开发者后台获取', type: 'password', icon: <Key size={12} /> },
  }
  const inputCfg = inputLabels[strategy]

  return (
    <>
      <div className={cx('card p-4 transition-all duration-200 hover:shadow-md', cfg.bg)}>
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5">
            <div className={cx('w-9 h-9 rounded-xl flex items-center justify-center text-base font-bold border', meta.color)}>
              {meta.emoji}
            </div>
            <div>
              <p className="text-sm font-semibold text-ink-800">{meta.name}</p>
              <div className="flex items-center gap-1 mt-0.5">
                <StatusIcon size={11} className={cfg.color} />
                <span className={cx('text-[11px] font-medium', cfg.color)}>{cfg.label}</span>
              </div>
            </div>
          </div>
          {memCount !== undefined && memCount > 0 && (
            <div className="text-right flex-shrink-0">
              <p className="text-lg font-display font-semibold text-ink-700 tabular-nums">{memCount}</p>
              <p className="text-[10px] text-ink-400">条记忆</p>
            </div>
          )}
        </div>

        {/* Last sync */}
        {status.last_refresh && (
          <p className="text-[11px] text-ink-400 mb-2">上次连接：{relativeTime(status.last_refresh)}</p>
        )}

        {/* Cookie expiry warning */}
        {status.expires_at && platformId === 'xiaohongshu' && isConnected && (
          <div className="text-[11px] text-amber-600 bg-amber-50 rounded-lg px-2.5 py-1.5 mb-3 border border-amber-100">
            Cookie 将于 {relativeTime(status.expires_at)} 过期，请及时更新
          </div>
        )}

        {/* Input form */}
        {showInput && inputCfg && (
          <div className="mb-3 space-y-2 animate-slide-up">
            <div className="flex items-center gap-1.5 text-xs text-ink-500 mb-1">
              {inputCfg.icon}
              <span>{inputCfg.label}</span>
            </div>
            <p className="text-[11px] text-ink-400 leading-relaxed bg-ink-50 rounded-lg p-2 border border-ink-100">
              {AUTH_HINTS[platformId]}
            </p>
            <input
              type={inputCfg.type}
              value={inputVal}
              onChange={e => setInputVal(e.target.value)}
              placeholder={inputCfg.placeholder}
              className="input-base text-xs font-mono"
              onKeyDown={e => e.key === 'Enter' && handleSave()}
            />
            <div className="flex gap-2">
              <button onClick={handleSave} disabled={busy || !inputVal.trim()} className="btn-primary text-xs flex-1 justify-center">
                {busy ? <Loader2 size={12} className="animate-spin" /> : '保存'}
              </button>
              <button onClick={() => { setShowInput(false); setInputVal('') }} className="btn-ghost text-xs">取消</button>
            </div>
          </div>
        )}

        {/* Auth strategy indicator */}
        <div className="flex items-center gap-1.5 mb-3">
          {strategy === 'qrcode' && <span className="text-[10px] px-2 py-0.5 rounded bg-teal-50 text-teal-600 border border-teal-100 flex items-center gap-1"><QrCode size={9} />扫码登录</span>}
          {strategy === 'pat'    && <span className="text-[10px] px-2 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-100 flex items-center gap-1"><Key size={9} />Personal Access Token</span>}
          {strategy === 'cookie' && <span className="text-[10px] px-2 py-0.5 rounded bg-amber-50 text-amber-600 border border-amber-100 flex items-center gap-1"><Cookie size={9} />Cookie 模式</span>}
          {strategy === 'apikey' && <span className="text-[10px] px-2 py-0.5 rounded bg-purple-50 text-purple-600 border border-purple-100 flex items-center gap-1"><Key size={9} />API Key</span>}
          {(strategy === 'oauth' || strategy === 'pocket_oauth') && <span className="text-[10px] px-2 py-0.5 rounded bg-green-50 text-green-600 border border-green-100 flex items-center gap-1"><ExternalLink size={9} />OAuth</span>}
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          {!isConnected || needsReauth ? (
            <button onClick={handleConnect} disabled={busy} className="btn-primary text-xs flex-1 justify-center">
              {busy ? <Loader2 size={12} className="animate-spin" />
                    : strategy === 'qrcode' ? <><QrCode size={12} />{needsReauth ? '重新扫码' : '扫码连接'}</>
                    : <><ExternalLink size={12} />{needsReauth ? '重新授权' : '连接'}</>}
            </button>
          ) : (
            <>
              {(strategy === 'cookie' || strategy === 'pat' || strategy === 'apikey') && (
                <button onClick={() => setShowInput(true)} className="btn-outline text-xs flex-1 justify-center text-xs">
                  更新凭证
                </button>
              )}
              <button onClick={handleRevoke} disabled={busy} className="btn-danger text-xs px-2.5">
                {busy ? <Loader2 size={12} className="animate-spin" /> : <Unlink size={13} />}
              </button>
            </>
          )}
        </div>
      </div>

      {/* QR code modal */}
      {showQR && (
        <QRCodeModal
          platform={platformId}
          onClose={() => setShowQR(false)}
          onSuccess={() => updateStatus(platformId, { status: 'connected' })}
        />
      )}
    </>
  )
}
