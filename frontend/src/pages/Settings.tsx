// pages/Settings.tsx — v2.0.0 侧边栏导航 + 分区折叠 + 数据管理
import { useState, useEffect } from 'react'
import {
  Save, CheckCircle, XCircle, Loader2, RefreshCw,
  ChevronDown, ChevronRight, Cpu, Search, Mic, Star,
  Database, Info, AlertTriangle, Download, Upload, Trash2,
  ExternalLink, Github, FileText
} from 'lucide-react'
import { getConfig, postConfig, testLLM, testEmbedding, getStats, exportMemories, importMemories, cleanupOldMemories, resetConfig, clearAllMemories } from '../api/apiClient'
import { useToastStore, useStatsStore } from '../store'
import { cx } from '../utils'
import type { ConfigMap, LLMTestResult } from '../api/types'

// ── Types ──────────────────────────────────────────────────────────────────────
type SectionId = 'model' | 'search' | 'voice' | 'scoring' | 'data' | 'about' | 'danger'

interface SectionItem {
  key: string; label: string; hint?: string
  type: 'select' | 'input' | 'toggle' | 'number' | 'password' | 'divider'
  options?: { label: string; value: string }[]
  placeholder?: string
}
interface Section {
  id: SectionId; title: string; icon: typeof Cpu
  items: SectionItem[]
}

// ── Section Definitions ────────────────────────────────────────────────────────
const SECTIONS: Section[] = [
  {
    id: 'model', title: '模型配置', icon: Cpu,
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
      { key: '_divider1', label: '', type: 'divider' } as any,
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
    id: 'search', title: '同步与检索', icon: Search,
    items: [
      { key: 'SYNC_INTERVAL_HOURS', label: '自动同步间隔（小时）', type: 'number', hint: '0 = 禁用自动同步', placeholder: '6' },
      { key: 'TOP_K_RESULTS', label: '问答最大返回条数', type: 'number', placeholder: '5' },
    ],
  },
  {
    id: 'scoring', title: '重要性评分', icon: Star,
    items: [
      { key: 'IMPORTANCE_DECAY_RATE', label: '时间衰减率（每天）', type: 'input', hint: '0.99 = 每天衰减 1%，越小衰减越快', placeholder: '0.99' },
      { key: 'IMPORTANCE_DECAY_DAYS_THRESHOLD', label: '开始衰减阈值（天）', type: 'number', hint: '超过多少天未访问才开始衰减', placeholder: '30' },
    ],
  },
  {
    id: 'voice', title: '语音识别与播报', icon: Mic,
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
      { key: 'TTS_ENABLED', label: '启用语音播报', type: 'toggle', hint: '使用 XTTS 将问答结果转为语音' },
      {
        key: 'TTS_LANGUAGE', label: '播报语言', type: 'select',
        options: [{ label: '中文', value: 'zh-cn' }, { label: '英文', value: 'en' }, { label: '日文', value: 'ja' }],
      },
    ],
  },
]

// ── Nav Items ───────────────────────────────────────────────────────────────────
const NAV_ITEMS: { id: SectionId; label: string; icon: typeof Cpu }[] = [
  { id: 'model', label: '模型配置', icon: Cpu },
  { id: 'search', label: '同步与检索', icon: Search },
  { id: 'voice', label: '语音', icon: Mic },
  { id: 'scoring', label: '评分', icon: Star },
  { id: 'data', label: '数据管理', icon: Database },
  { id: 'about', label: '关于', icon: Info },
  { id: 'danger', label: '危险操作', icon: AlertTriangle },
]

// ── Collapsible Section ────────────────────────────────────────────────────────
function CollapsibleSection({
  section, values, dirty, set
}: {
  section: Section
  values: ConfigMap
  dirty: Set<string>
  set: (key: string, val: string | boolean | number) => void
}) {
  const [open, setOpen] = useState(true)

  return (
    <div className="card overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 hover:bg-dark-elevated transition-colors"
      >
        <span className="text-sm font-medium text-gray-200">{section.title}</span>
        {open ? <ChevronDown size={14} className="text-gray-500" /> : <ChevronRight size={14} className="text-gray-500" />}
      </button>
      {open && (
        <div className="divide-y divide-dark-border">
          {section.items.map(item => {
            if (item.type === 'divider') return <div key={item.key} className="h-px bg-dark-border mx-4 my-1" />
            return (
              <div key={item.key} className={cx('flex items-start justify-between gap-4 p-4', dirty.has(item.key) && 'bg-warning/5')}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-gray-200">{item.label}</p>
                    {dirty.has(item.key) && <span className="text-[9px] text-warning font-bold bg-warning/10 px-1.5 py-0.5 rounded">已修改</span>}
                  </div>
                  {item.hint && <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{item.hint}</p>}
                </div>
                <div className="flex-shrink-0 w-52">
                  {item.type === 'select' && (
                    <select value={String(values[item.key] ?? item.options?.[0]?.value ?? '')}
                      onChange={e => set(item.key, e.target.value)} className="input-base text-xs">
                      {item.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  )}
                  {(item.type === 'input' || item.type === 'password') && (
                    <input
                      type={item.type === 'password' ? 'password' : 'text'}
                      value={String(values[item.key] ?? '')}
                      onChange={e => set(item.key, e.target.value)}
                      placeholder={item.placeholder ?? ''}
                      className="input-base text-xs font-mono"
                    />
                  )}
                  {item.type === 'number' && (
                    <input type="number" value={Number(values[item.key] ?? 0)}
                      onChange={e => set(item.key, Number(e.target.value))}
                      placeholder={item.placeholder} min={0} className="input-base text-xs" />
                  )}
                  {item.type === 'toggle' && (
                    <button onClick={() => set(item.key, !Boolean(values[item.key]))}
                      className={cx('relative w-10 h-6 rounded-full transition-colors duration-200',
                        values[item.key] ? 'bg-ai' : 'bg-dark-borderLight')}>
                      <span className={cx('absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200',
                        values[item.key] ? 'translate-x-5' : 'translate-x-1')} />
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────────────────────────
export default function Settings() {
  const push = useToastStore(s => s.push)
  const stats = useStatsStore(s => s.stats)

  const [values, setValues] = useState<ConfigMap>({})
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [llmTest, setLlmTest] = useState<LLMTestResult | null>(null)
  const [embTest, setEmbTest] = useState<LLMTestResult | null>(null)
  const [testing, setTesting] = useState<'llm' | 'emb' | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeSection, setActiveSection] = useState<SectionId>('model')
  const [confirming, setConfirming] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getConfig(), getStats().catch(() => null)])
      .then(([cfg]) => { setValues(cfg); setLoading(false) })
      .catch(() => { push('加载配置失败', 'error'); setLoading(false) })
  }, [])

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

  async function handleExportMemories() {
    try {
      const blob = await exportMemories()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `memories_export_${new Date().toISOString().slice(0,10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      push('导出成功', 'success')
    } catch {
      push('导出失败', 'error')
    }
  }

  async function handleImportMemories() {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      try {
        const result = await importMemories(file)
        push(`导入完成：新增 ${result.imported}，更新 ${result.updated}，失败 ${result.failed}`, 'success')
      } catch {
        push('导入失败', 'error')
      }
    }
    input.click()
  }

  async function handleClearOldMemories() {
    if (confirming !== 'clearold') { setConfirming('clearold'); return }
    setConfirming(null)
    try {
      const result = await cleanupOldMemories(180)
      push(`已清理 ${result.deleted_count} 条旧记忆`, 'success')
    } catch {
      push('清理失败', 'error')
    }
  }

  async function handleResetConfig() {
    if (confirming !== 'reset') { setConfirming('reset'); return }
    setConfirming(null)
    try {
      await resetConfig()
      push('配置已重置', 'success')
      const cfg = await getConfig()
      setValues(cfg)
      setDirty(new Set())
    } catch {
      push('重置失败', 'error')
    }
  }

  async function handleClearAllMemories() {
    if (confirming !== 'clear') { setConfirming('clear'); return }
    setConfirming(null)
    try {
      const result = await clearAllMemories(true)
      push(`已删除 ${result.deleted_count} 条记忆`, 'success')
    } catch {
      push('清空失败', 'error')
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-full bg-dark-bg">
      <Loader2 size={24} className="animate-spin text-gray-500" />
    </div>
  )

  return (
    <div className="flex h-full bg-dark-bg">
      {/* ── Left Sidebar ── */}
      <nav className="w-44 flex-shrink-0 border-r border-dark-border bg-dark-surface overflow-y-auto scrollbar-none">
        <div className="py-4">
          <p className="px-4 mb-3 text-[10px] font-semibold text-gray-500 uppercase tracking-wider">设置分类</p>
          {NAV_ITEMS.map(item => {
            const Icon = item.icon
            const isActive = activeSection === item.id
            const isDanger = item.id === 'danger'
            return (
              <button
                key={item.id}
                onClick={() => setActiveSection(item.id)}
                className={cx(
                  'w-full flex items-center gap-2.5 px-4 py-2.5 text-sm transition-colors',
                  isActive
                    ? 'bg-ai/10 text-ai border-r-2 border-ai'
                    : isDanger
                      ? 'text-danger/70 hover:text-danger hover:bg-danger/5'
                      : 'text-gray-400 hover:text-gray-200 hover:bg-dark-elevated'
                )}
              >
                <Icon size={15} />
                <span className="text-xs">{item.label}</span>
              </button>
            )
          })}
        </div>

        {/* Connection Status */}
        <div className="mx-3 mb-4 p-3 rounded-xl bg-dark-elevated border border-dark-border">
          <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">连接状态</p>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">LLM</span>
              <button onClick={handleTestLLM} disabled={testing === 'llm'} className="text-[10px] text-ai hover:text-ai-light flex items-center gap-1">
                {testing === 'llm' ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
                测试
              </button>
            </div>
            {llmTest && (
              <div className={cx('flex items-center gap-1 text-[10px]', llmTest.ok ? 'text-success' : 'text-danger')}>
                {llmTest.ok ? <CheckCircle size={10} /> : <XCircle size={10} />}
                <span className="truncate">{llmTest.ok ? `${llmTest.provider}` : (llmTest.error ?? '失败')}</span>
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">Embedding</span>
              <button onClick={handleTestEmb} disabled={testing === 'emb'} className="text-[10px] text-ai hover:text-ai-light flex items-center gap-1">
                {testing === 'emb' ? <Loader2 size={10} className="animate-spin" /> : <RefreshCw size={10} />}
                测试
              </button>
            </div>
            {embTest && (
              <div className={cx('flex items-center gap-1 text-[10px]', embTest.ok ? 'text-success' : 'text-danger')}>
                {embTest.ok ? <CheckCircle size={10} /> : <XCircle size={10} />}
                <span className="truncate">{embTest.ok ? `${embTest.provider} · ${embTest.dim}维` : (embTest.error ?? '失败')}</span>
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* ── Main Content ── */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center justify-between px-6 py-4 border-b border-dark-border flex-shrink-0">
          <div>
            <h1 className="font-semibold text-gray-100">系统设置</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              {dirty.size > 0 ? <span className="text-warning">{dirty.size} 项未保存</span> : '配置已同步'}
            </p>
          </div>
          <button onClick={handleSave} disabled={saving || dirty.size === 0}
            className={cx('btn text-xs gap-1.5', dirty.size > 0 ? 'btn-primary' : 'btn-ghost opacity-50 cursor-not-allowed')}>
            {saving ? <><Loader2 size={13} className="animate-spin" />保存中...</> : <><Save size={13} />保存配置</>}
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5 scrollbar-none">
          {/* ── Model Config ── */}
          {activeSection === 'model' && (
            <div className="space-y-4 max-w-2xl">
              <p className="text-xs text-gray-500">配置 LLM 模型和 Embedding 提供商。平台凭证请在「平台接入」页面管理。</p>
              {SECTIONS.filter(s => s.id === 'model').map(section => (
                <CollapsibleSection key={section.id} section={section} values={values} dirty={dirty} set={set} />
              ))}
            </div>
          )}

          {/* ── Search & Sync ── */}
          {activeSection === 'search' && (
            <div className="space-y-4 max-w-2xl">
              <p className="text-xs text-gray-500">配置自动同步间隔和问答检索参数。</p>
              {SECTIONS.filter(s => s.id === 'search').map(section => (
                <CollapsibleSection key={section.id} section={section} values={values} dirty={dirty} set={set} />
              ))}
            </div>
          )}

          {/* ── Voice ── */}
          {activeSection === 'voice' && (
            <div className="space-y-4 max-w-2xl">
              <p className="text-xs text-gray-500">配置 Whisper 语音识别和 TTS 语音播报功能。</p>
              {SECTIONS.filter(s => s.id === 'voice').map(section => (
                <CollapsibleSection key={section.id} section={section} values={values} dirty={dirty} set={set} />
              ))}
            </div>
          )}

          {/* ── Scoring ── */}
          {activeSection === 'scoring' && (
            <div className="space-y-4 max-w-2xl">
              <p className="text-xs text-gray-500">配置记忆重要性评分的时间衰减算法参数。</p>
              {SECTIONS.filter(s => s.id === 'scoring').map(section => (
                <CollapsibleSection key={section.id} section={section} values={values} dirty={dirty} set={set} />
              ))}
            </div>
          )}

          {/* ── Data Management ── */}
          {activeSection === 'data' && (
            <div className="space-y-4 max-w-2xl">
              <p className="text-xs text-gray-500">导入、导出和清理您的记忆数据。</p>

              <div className="card overflow-hidden">
                <div className="p-4 border-b border-dark-border">
                  <p className="text-sm font-medium text-gray-200">当前存储状态</p>
                  <p className="text-xs text-gray-500 mt-1">
                    {stats ? `共 ${stats.total} 条记忆` : '加载中...'}
                  </p>
                </div>
                <div className="divide-y divide-dark-border">
                  <div className="flex items-center justify-between p-4">
                    <div>
                      <p className="text-sm font-medium text-gray-200">导出记忆</p>
                      <p className="text-xs text-gray-500 mt-0.5">将所有记忆导出为 JSON 文件</p>
                    </div>
                    <button onClick={handleExportMemories} className="btn-ghost text-xs gap-1.5">
                      <Download size={13} />
                      导出
                    </button>
                  </div>
                  <div className="flex items-center justify-between p-4">
                    <div>
                      <p className="text-sm font-medium text-gray-200">导入记忆</p>
                      <p className="text-xs text-gray-500 mt-0.5">从 JSON 文件导入记忆数据</p>
                    </div>
                    <button onClick={handleImportMemories} className="btn-ghost text-xs gap-1.5">
                      <Upload size={13} />
                      导入
                    </button>
                  </div>
                  <div className="flex items-center justify-between p-4">
                    <div>
                      <p className="text-sm font-medium text-gray-200">清理旧记忆</p>
                      <p className="text-xs text-gray-500 mt-0.5">删除超过 180 天未访问的低重要性记忆</p>
                    </div>
                    <button onClick={handleClearOldMemories} className="btn-ghost text-xs gap-1.5">
                      <Trash2 size={13} />
                      清理
                    </button>
                  </div>
                </div>
              </div>

              {/* Storage Breakdown */}
              {stats && (
                <div className="card p-4">
                  <p className="text-sm font-semibold text-gray-200 mb-3">记忆来源分布</p>
                  <div className="space-y-2">
                    {stats.by_platform.slice(0, 8).map(p => (
                      <div key={p.platform} className="flex items-center justify-between">
                        <span className="text-xs text-gray-400">{p.platform}</span>
                        <span className="text-xs font-medium text-gray-300">{p.count} 条</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── About ── */}
          {activeSection === 'about' && (
            <div className="space-y-4 max-w-2xl">
              <div className="card p-6">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl bg-ai/10 flex items-center justify-center flex-shrink-0">
                    <Cpu size={24} className="text-ai" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-gray-100">Personal AI Memory</h2>
                    <p className="text-xs text-gray-500 mt-1">版本 1.2.0</p>
                    <p className="text-sm text-gray-400 mt-3 leading-relaxed">
                      您的私人 AI 知识库，将多个平台的收藏整合为可对话的记忆系统。
                    </p>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-dark-border space-y-3">
                  <a href="https://github.com" target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm text-gray-400 hover:text-ai transition-colors">
                    <Github size={14} />
                    GitHub 项目主页
                    <ExternalLink size={12} className="ml-1 opacity-50" />
                  </a>
                  <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm text-gray-400 hover:text-ai transition-colors">
                    <FileText size={14} />
                    API 接口文档
                    <ExternalLink size={12} className="ml-1 opacity-50" />
                  </a>
                </div>
              </div>

              <div className="card p-4">
                <p className="text-sm font-semibold text-gray-200 mb-3">技术栈</p>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    ['前端', 'React + TypeScript + Vite'],
                    ['后端', 'FastAPI + Python'],
                    ['向量检索', 'FAISS'],
                    ['数据库', 'SQLite'],
                    ['AI 模型', 'OpenAI / Anthropic / Ollama'],
                  ].map(([label, value]) => (
                    <div key={label} className="flex items-center gap-2">
                      <span className="text-[10px] text-gray-500 w-12">{label}</span>
                      <span className="text-xs text-gray-300">{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ── Danger Zone ── */}
          {activeSection === 'danger' && (
            <div className="space-y-4 max-w-2xl">
              <div className="p-3 rounded-xl bg-danger/10 border border-danger/20">
                <p className="text-xs text-danger font-medium">危险操作区</p>
                <p className="text-[10px] text-danger/70 mt-1">以下操作不可逆，请谨慎操作。</p>
              </div>

              <div className="card overflow-hidden border-danger/20">
                <div className="flex items-center justify-between p-4">
                  <div>
                    <p className="text-sm font-medium text-gray-200">重置所有配置</p>
                    <p className="text-xs text-gray-500 mt-0.5">将所有设置恢复为默认值</p>
                  </div>
                  <button
                    onClick={handleResetConfig}
                    className={cx('text-xs gap-1.5 px-3 py-1.5 rounded-lg transition-colors',
                      confirming === 'reset'
                        ? 'bg-danger text-white'
                        : 'btn-ghost text-danger border border-danger/30 hover:bg-danger/10'
                    )}
                  >
                    {confirming === 'reset' ? '确认重置' : '重置'}
                  </button>
                </div>
              </div>

              <div className="card overflow-hidden border-danger/20">
                <div className="flex items-center justify-between p-4">
                  <div>
                    <p className="text-sm font-medium text-gray-200">清空所有记忆</p>
                    <p className="text-xs text-gray-500 mt-0.5">删除所有记忆数据，此操作不可恢复</p>
                  </div>
                  <button
                    onClick={handleClearAllMemories}
                    className={cx('text-xs gap-1.5 px-3 py-1.5 rounded-lg transition-colors',
                      confirming === 'clear'
                        ? 'bg-danger text-white'
                        : 'btn-ghost text-danger border border-danger/30 hover:bg-danger/10'
                    )}
                  >
                    {confirming === 'clear' ? '确认清空' : '清空'}
                  </button>
                </div>
              </div>
            </div>
          )}

          <div className="pb-8" />
        </div>
      </div>
    </div>
  )
}
