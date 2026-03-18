// pages/Settings.tsx — v1.2.0  真正读写 /config API
import { useState, useEffect } from 'react'
import { Save, ExternalLink, CheckCircle, XCircle, Loader2, RefreshCw, Settings as SettingsIcon } from 'lucide-react'
import { getConfig, postConfig, testLLM, testEmbedding } from '../api/apiClient'
import { useToastStore } from '../store'
import { cx } from '../utils'
import type { ConfigMap, LLMTestResult } from '../api/types'

interface SectionItem {
  key: string; label: string; hint?: string
  type: 'select' | 'input' | 'toggle' | 'number' | 'password'
  options?: { label: string; value: string }[]
  placeholder?: string
}
interface Section { title: string; items: SectionItem[] }

const SECTIONS: Section[] = [
  {
    title: 'LLM 模型',
    items: [
      {
        key: 'LLM_PROVIDER', label: 'LLM 提供商', type: 'select',
        hint: 'auto = 自动检测（推荐）',
        options: [
          { label: '自动检测 (auto)', value: 'auto' },
          { label: 'OpenAI', value: 'openai' },
          { label: 'Anthropic (Claude)', value: 'anthropic' },
          { label: 'Azure OpenAI', value: 'azure' },
          { label: 'Ollama (本地)', value: 'ollama' },
          { label: '本地 OpenAI 兼容服务', value: 'openai_compatible' },
        ],
      },
      {
        key: 'LLM_MODEL', label: '模型名称', type: 'input',
        hint: 'OpenAI: gpt-4o-mini | Anthropic: claude-3-5-haiku-20241022 | Ollama: qwen2.5:7b',
        placeholder: 'gpt-4o-mini',
      },
      {
        key: 'LLM_API_KEY', label: 'API Key', type: 'password',
        hint: 'OpenAI / Azure 的 API Key（Anthropic 单独配置下方字段）',
        placeholder: 'sk-...',
      },
      {
        key: 'ANTHROPIC_API_KEY', label: 'Anthropic API Key', type: 'password',
        hint: '使用 Claude 系列模型时填写',
        placeholder: 'sk-ant-...',
      },
      {
        key: 'LLM_BASE_URL', label: '自定义 API 端点', type: 'input',
        hint: 'Ollama: http://localhost:11434/v1 | Azure: https://xxx.openai.azure.com | LM Studio: http://localhost:1234/v1',
        placeholder: '留空使用默认端点',
      },
      {
        key: 'AZURE_OPENAI_API_VERSION', label: 'Azure API 版本', type: 'input',
        hint: '仅 Azure OpenAI 需要填写', placeholder: '2024-02-01',
      },
    ],
  },
  {
    title: 'Embedding 向量化',
    items: [
      {
        key: 'EMBEDDING_PROVIDER', label: 'Embedding 提供商', type: 'select',
        hint: '留空则与 LLM 使用同一提供商',
        options: [
          { label: '同 LLM 提供商', value: '' },
          { label: 'OpenAI', value: 'openai' },
          { label: 'Ollama', value: 'ollama' },
          { label: 'OpenAI 兼容服务', value: 'openai_compatible' },
        ],
      },
      {
        key: 'EMBEDDING_MODEL', label: 'Embedding 模型', type: 'input',
        hint: 'OpenAI: text-embedding-3-small | Ollama: nomic-embed-text',
        placeholder: 'text-embedding-3-small',
      },
    ],
  },
  {
    title: '平台认证凭证',
    items: [
      { key: 'YOUTUBE_CLIENT_ID', label: 'YouTube Client ID', type: 'input', placeholder: '在 Google Cloud Console 创建' },
      { key: 'YOUTUBE_CLIENT_SECRET', label: 'YouTube Client Secret', type: 'password', placeholder: '' },
      { key: 'TWITTER_CLIENT_ID', label: 'Twitter Client ID', type: 'input', placeholder: '在 Twitter Developer Portal 创建' },
      { key: 'TWITTER_CLIENT_SECRET', label: 'Twitter Client Secret', type: 'password', placeholder: '' },
      { key: 'POCKET_CONSUMER_KEY', label: 'Pocket Consumer Key', type: 'password', placeholder: '在 Pocket Developer 创建应用获取' },
    ],
  },
  {
    title: '同步与检索',
    items: [
      { key: 'SYNC_INTERVAL_HOURS', label: '自动同步间隔（小时）', type: 'number', hint: '0 = 禁用自动同步', placeholder: '6' },
      { key: 'TOP_K_RESULTS', label: '问答最大返回条数', type: 'number', placeholder: '5' },
    ],
  },
  {
    title: '重要性评分',
    items: [
      { key: 'IMPORTANCE_DECAY_RATE', label: '时间衰减率（每天）', type: 'input', hint: '0.99 = 每天衰减 1%，越小衰减越快', placeholder: '0.99' },
      { key: 'IMPORTANCE_DECAY_DAYS_THRESHOLD', label: '开始衰减阈值（天）', type: 'number', hint: '超过多少天未访问才开始衰减', placeholder: '30' },
    ],
  },
  {
    title: '语音识别 (Whisper)',
    items: [
      {
        key: 'WHISPER_MODEL_SIZE', label: 'Whisper 模型规格', type: 'select',
        hint: '规格越大越准确，消耗资源越多',
        options: [
          { label: 'tiny（最快，低精度）', value: 'tiny' },
          { label: 'base（推荐）', value: 'base' },
          { label: 'small', value: 'small' },
          { label: 'medium', value: 'medium' },
          { label: 'large（最准，需大显存）', value: 'large' },
        ],
      },
      {
        key: 'WHISPER_DEVICE', label: '推理设备', type: 'select',
        options: [{ label: 'CPU', value: 'cpu' }, { label: 'CUDA (GPU)', value: 'cuda' }, { label: 'MPS (Apple Silicon)', value: 'mps' }],
      },
    ],
  },
  {
    title: '语音播报 (TTS)',
    items: [
      { key: 'TTS_ENABLED', label: '启用语音播报', type: 'toggle', hint: '使用 XTTS 将问答结果转为语音' },
      {
        key: 'TTS_LANGUAGE', label: '播报语言', type: 'select',
        options: [{ label: '中文', value: 'zh-cn' }, { label: '英文', value: 'en' }, { label: '日文', value: 'ja' }],
      },
    ],
  },
]

export default function Settings() {
  const push = useToastStore(s => s.push)
  const [values, setValues] = useState<ConfigMap>({})
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [llmTest, setLlmTest] = useState<LLMTestResult | null>(null)
  const [embTest, setEmbTest] = useState<LLMTestResult | null>(null)
  const [testing, setTesting] = useState<'llm' | 'emb' | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getConfig().then(cfg => { setValues(cfg); setLoading(false) })
      .catch(() => { push('加载配置失败', 'error'); setLoading(false) })
  }, [])

  function get(key: string, fallback: string | boolean | number = '') {
    return values[key] ?? fallback
  }

  function set(key: string, val: string | boolean | number) {
    setValues(prev => ({ ...prev, [key]: val }))
    setDirty(prev => new Set(prev).add(key))
  }

  async function handleSave() {
    if (dirty.size === 0) return
    setSaving(true)
    try {
      const updates: ConfigMap = {}
      dirty.forEach(k => { updates[k] = values[k] })
      await postConfig(updates)
      setDirty(new Set())
      push(`已保存 ${dirty.size} 项配置`, 'success')
    } catch { push('保存失败', 'error') }
    finally { setSaving(false) }
  }

  async function handleTestLLM() {
    setTesting('llm'); setLlmTest(null)
    try { setLlmTest(await testLLM()) }
    catch { setLlmTest({ ok: false, provider: 'unknown', error: '连接失败' }) }
    finally { setTesting(null) }
  }

  async function handleTestEmb() {
    setTesting('emb'); setEmbTest(null)
    try { setEmbTest(await testEmbedding()) }
    catch { setEmbTest({ ok: false, provider: 'unknown', error: '连接失败' }) }
    finally { setTesting(null) }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <Loader2 size={24} className="animate-spin text-ink-400" />
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <header className="flex items-center justify-between px-6 py-4 border-b border-ink-100 bg-white/80 backdrop-blur-sm flex-shrink-0">
        <div>
          <h1 className="font-display font-semibold text-ink-800">系统设置</h1>
          <p className="text-xs text-ink-400 mt-0.5">
            {dirty.size > 0 ? <span className="text-warning">{dirty.size} 项未保存</span> : '配置已同步'}
          </p>
        </div>
        <button onClick={handleSave} disabled={saving || dirty.size === 0}
          className={cx('btn text-xs gap-1.5', dirty.size > 0 ? 'btn-primary' : 'btn-ghost opacity-50 cursor-not-allowed')}>
          {saving ? <><Loader2 size={13} className="animate-spin" />保存中...</> : <><Save size={13} />保存配置</>}
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6 scrollbar-none max-w-2xl">

        {/* LLM + Embedding connection tests */}
        <div className="card p-4">
          <p className="text-sm font-semibold text-ink-700 mb-3">连接测试</p>
          <div className="grid grid-cols-2 gap-3">
            {/* LLM test */}
            <div className="p-3 rounded-xl bg-ink-50 border border-ink-100">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-ink-700">LLM</span>
                <button onClick={handleTestLLM} disabled={testing === 'llm'}
                  className="text-[10px] text-accent hover:text-accent-dark flex items-center gap-1">
                  {testing === 'llm' ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
                  测试
                </button>
              </div>
              {llmTest ? (
                <div className={cx('flex items-center gap-1.5 text-xs', llmTest.ok ? 'text-success' : 'text-danger')}>
                  {llmTest.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
                  <span>{llmTest.ok ? `${llmTest.provider} · ${llmTest.model}` : (llmTest.error ?? '失败')}</span>
                </div>
              ) : (
                <p className="text-[11px] text-ink-400">点击「测试」检查连接</p>
              )}
            </div>
            {/* Embedding test */}
            <div className="p-3 rounded-xl bg-ink-50 border border-ink-100">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-ink-700">Embedding</span>
                <button onClick={handleTestEmb} disabled={testing === 'emb'}
                  className="text-[10px] text-accent hover:text-accent-dark flex items-center gap-1">
                  {testing === 'emb' ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
                  测试
                </button>
              </div>
              {embTest ? (
                <div className={cx('flex items-center gap-1.5 text-xs', embTest.ok ? 'text-success' : 'text-danger')}>
                  {embTest.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
                  <span>{embTest.ok ? `${embTest.provider} · ${embTest.dim}维` : (embTest.error ?? '失败')}</span>
                </div>
              ) : (
                <p className="text-[11px] text-ink-400">点击「测试」检查连接</p>
              )}
            </div>
          </div>
        </div>

        {/* Config sections */}
        {SECTIONS.map(section => (
          <section key={section.title}>
            <h2 className="text-xs font-semibold text-ink-400 uppercase tracking-wider mb-3">{section.title}</h2>
            <div className="card divide-y divide-ink-100">
              {section.items.map(item => (
                <div key={item.key} className={cx('flex items-start justify-between gap-4 p-4', dirty.has(item.key) && 'bg-amber-50/40')}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-ink-800">{item.label}</p>
                      {dirty.has(item.key) && <span className="text-[9px] text-warning font-bold bg-warning/10 px-1.5 py-0.5 rounded">已修改</span>}
                    </div>
                    {item.hint && <p className="text-xs text-ink-400 mt-0.5 leading-relaxed">{item.hint}</p>}
                  </div>
                  <div className="flex-shrink-0 w-52">
                    {item.type === 'select' && (
                      <select value={String(get(item.key, item.options?.[0]?.value ?? ''))}
                        onChange={e => set(item.key, e.target.value)} className="input-base text-xs">
                        {item.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    )}
                    {(item.type === 'input' || item.type === 'password') && (
                      <input
                        type={item.type === 'password' ? 'password' : 'text'}
                        value={String(get(item.key, ''))}
                        onChange={e => set(item.key, e.target.value)}
                        placeholder={item.placeholder ?? ''}
                        className="input-base text-xs font-mono"
                      />
                    )}
                    {item.type === 'number' && (
                      <input type="number" value={Number(get(item.key, 0))}
                        onChange={e => set(item.key, Number(e.target.value))}
                        placeholder={item.placeholder} min={0} className="input-base text-xs" />
                    )}
                    {item.type === 'toggle' && (
                      <button onClick={() => set(item.key, !Boolean(get(item.key, false)))}
                        className={cx('relative w-10 h-6 rounded-full transition-colors duration-200',
                          get(item.key, false) ? 'bg-accent' : 'bg-ink-200')}>
                        <span className={cx('absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200',
                          get(item.key, false) ? 'translate-x-5' : 'translate-x-1')} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}

        {/* Links */}
        <section>
          <h2 className="text-xs font-semibold text-ink-400 uppercase tracking-wider mb-3">文档 & 工具</h2>
          <div className="card divide-y divide-ink-100">
            {[
              { label: 'API 接口文档', href: 'http://localhost:8000/docs', hint: 'FastAPI 自动生成，所有接口一览' },
              { label: '后端健康检查', href: 'http://localhost:8000/health', hint: '查看后端服务状态和记忆总数' },
              { label: 'Google Cloud Console', href: 'https://console.cloud.google.com/', hint: '创建 YouTube OAuth 应用' },
              { label: 'GitHub Token 设置', href: 'https://github.com/settings/tokens', hint: '创建 Personal Access Token' },
              { label: 'Twitter 开发者后台', href: 'https://developer.twitter.com/en/portal/dashboard', hint: '创建 Twitter 应用获取 Client ID' },
              { label: 'Pocket 开发者后台', href: 'https://getpocket.com/developer/apps/', hint: '创建 Pocket 应用获取 Consumer Key' },
            ].map(link => (
              <a key={link.href} href={link.href} target="_blank" rel="noopener noreferrer"
                className="flex items-center justify-between p-4 hover:bg-ink-50 transition-colors group">
                <div>
                  <p className="text-sm font-medium text-ink-800">{link.label}</p>
                  <p className="text-xs text-ink-400 mt-0.5">{link.hint}</p>
                </div>
                <ExternalLink size={14} className="text-ink-400 group-hover:text-accent transition-colors" />
              </a>
            ))}
          </div>
        </section>

        <div className="pb-8" />
      </div>
    </div>
  )
}
