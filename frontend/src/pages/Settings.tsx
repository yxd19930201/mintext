import { useEffect, useState } from 'react'
import { aiApi } from '../services/api/aiApi'
import type { AIConfig, AIPromptPreset } from '../types/models'

type Tab = 'configs' | 'presets'

const emptyConfig = { name: '', base_url: '', api_key: '', model: '', is_default: false }
const emptyPreset = { name: '', content: '', is_global: true }

export default function Settings() {
  const [tab, setTab] = useState<Tab>('configs')

  // AI Configs
  const [configs, setConfigs] = useState<AIConfig[]>([])
  const [configForm, setConfigForm] = useState(emptyConfig)
  const [editingConfig, setEditingConfig] = useState<AIConfig | null>(null)
  const [showConfigForm, setShowConfigForm] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)

  // Prompt Presets
  const [presets, setPresets] = useState<AIPromptPreset[]>([])
  const [presetForm, setPresetForm] = useState(emptyPreset)
  const [editingPreset, setEditingPreset] = useState<AIPromptPreset | null>(null)
  const [showPresetForm, setShowPresetForm] = useState(false)

  useEffect(() => {
    aiApi.listConfigs().then(r => setConfigs(r.data ?? []))
    aiApi.listPresets().then(r => setPresets(r.data ?? []))
  }, [])

  // --- Config handlers ---
  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault()
    if (editingConfig) {
      const res = await aiApi.updateConfig(editingConfig.id, configForm)
      setConfigs(configs.map(c => c.id === editingConfig.id ? res.data! : c))
    } else {
      const res = await aiApi.createConfig(configForm)
      setConfigs([...configs, res.data!])
    }
    setConfigForm(emptyConfig)
    setEditingConfig(null)
    setShowConfigForm(false)
  }

  const handleEditConfig = (c: AIConfig) => {
    setEditingConfig(c)
    setConfigForm({ name: c.name, base_url: c.base_url, api_key: c.api_key, model: c.model, is_default: c.is_default })
    setShowConfigForm(true)
  }

  const handleDeleteConfig = async (id: number) => {
    if (!confirm('确认删除此 AI 配置？')) return
    await aiApi.deleteConfig(id)
    setConfigs(configs.filter(c => c.id !== id))
  }

  // --- Preset handlers ---
  const handleSavePreset = async (e: React.FormEvent) => {
    e.preventDefault()
    if (editingPreset) {
      const res = await aiApi.updatePreset(editingPreset.id, presetForm)
      setPresets(presets.map(p => p.id === editingPreset.id ? res.data! : p))
    } else {
      const res = await aiApi.createPreset(presetForm)
      setPresets([...presets, res.data!])
    }
    setPresetForm(emptyPreset)
    setEditingPreset(null)
    setShowPresetForm(false)
  }

  const handleEditPreset = (p: AIPromptPreset) => {
    setEditingPreset(p)
    setPresetForm({ name: p.name, content: p.content, is_global: p.is_global })
    setShowPresetForm(true)
  }

  const handleDeletePreset = async (id: number) => {
    if (!confirm('确认删除此提示词预设？')) return
    await aiApi.deletePreset(id)
    setPresets(presets.filter(p => p.id !== id))
  }

  return (
    <div style={{ maxWidth: 760 }}>
      <h1 className="page-title">设置</h1>
      <p className="page-subtitle" style={{ marginBottom: 24 }}>管理 AI 模型配置和编剧提示词预设</p>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 24, borderBottom: '1px solid var(--border)', paddingBottom: 0 }}>
        {(['configs', 'presets'] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            padding: '8px 16px', background: 'none', border: 'none',
            borderBottom: `2px solid ${tab === t ? 'var(--accent)' : 'transparent'}`,
            color: tab === t ? 'var(--accent)' : 'var(--text-2)',
            fontWeight: tab === t ? 600 : 400, fontSize: 13, cursor: 'pointer',
            transition: 'all 0.15s', marginBottom: -1,
          }}>
            {t === 'configs' ? 'AI 模型配置' : '编剧提示词'}
          </button>
        ))}
      </div>

      {/* Tab: AI Configs */}
      {tab === 'configs' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
            <button className="btn btn-primary" onClick={() => { setEditingConfig(null); setConfigForm(emptyConfig); setShowConfigForm(!showConfigForm) }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
              新增配置
            </button>
          </div>

          {showConfigForm && (
            <div className="card" style={{ marginBottom: 20 }}>
              <div style={{ fontWeight: 600, marginBottom: 14, fontSize: 14 }}>{editingConfig ? '编辑配置' : '新增 AI 配置'}</div>
              <form onSubmit={handleSaveConfig}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
                  <div>
                    <label className="label">名称</label>
                    <input className="input" value={configForm.name} onChange={e => setConfigForm({ ...configForm, name: e.target.value })} placeholder="例：GPT-4o" required />
                  </div>
                  <div>
                    <label className="label">模型名</label>
                    <input className="input" value={configForm.model} onChange={e => setConfigForm({ ...configForm, model: e.target.value })} placeholder="例：gpt-4o" required />
                  </div>
                </div>
                <div style={{ marginBottom: 12 }}>
                  <label className="label">接口地址 (Base URL)</label>
                  <input className="input" value={configForm.base_url} onChange={e => setConfigForm({ ...configForm, base_url: e.target.value })} placeholder="https://api.openai.com/v1" required />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <label className="label">API Key</label>
                  <div style={{ position: 'relative' }}>
                    <input
                      className="input"
                      type={showApiKey ? 'text' : 'password'}
                      value={configForm.api_key}
                      onChange={e => setConfigForm({ ...configForm, api_key: e.target.value })}
                      placeholder="sk-..."
                      style={{ paddingRight: 40 }}
                      required
                    />
                    <button type="button" onClick={() => setShowApiKey(!showApiKey)} style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)' }}>
                      {showApiKey
                        ? <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                        : <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                      }
                    </button>
                  </div>
                </div>
                <div style={{ marginBottom: 14 }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                    <input type="checkbox" checked={configForm.is_default} onChange={e => setConfigForm({ ...configForm, is_default: e.target.checked })} />
                    设为默认配置
                  </label>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="submit" className="btn btn-primary">保存</button>
                  <button type="button" className="btn btn-ghost" onClick={() => setShowConfigForm(false)}>取消</button>
                </div>
              </form>
            </div>
          )}

          {configs.length === 0 && !showConfigForm && (
            <div className="empty-state">
              <p>还没有 AI 配置，点击「新增配置」添加 OpenAI 兼容接口</p>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {configs.map(c => (
              <div key={c.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{c.name}</span>
                    {c.is_default && <span className="badge" style={{ background: 'rgba(124,106,247,0.15)', color: 'var(--accent)' }}>默认</span>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>{c.base_url} · {c.model}</div>
                </div>
                <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => handleEditConfig(c)}>编辑</button>
                <button className="btn btn-danger" style={{ fontSize: 12 }} onClick={() => handleDeleteConfig(c.id)}>删除</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab: Prompt Presets */}
      {tab === 'presets' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
            <button className="btn btn-primary" onClick={() => { setEditingPreset(null); setPresetForm(emptyPreset); setShowPresetForm(!showPresetForm) }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
              新增预设
            </button>
          </div>

          {showPresetForm && (
            <div className="card" style={{ marginBottom: 20 }}>
              <div style={{ fontWeight: 600, marginBottom: 14, fontSize: 14 }}>{editingPreset ? '编辑预设' : '新增提示词预设'}</div>
              <form onSubmit={handleSavePreset}>
                <div style={{ marginBottom: 12 }}>
                  <label className="label">名称</label>
                  <input className="input" value={presetForm.name} onChange={e => setPresetForm({ ...presetForm, name: e.target.value })} placeholder="例：都市爱情编剧" required />
                </div>
                <div style={{ marginBottom: 12 }}>
                  <label className="label">提示词内容</label>
                  <textarea
                    className="textarea"
                    value={presetForm.content}
                    onChange={e => setPresetForm({ ...presetForm, content: e.target.value })}
                    rows={6}
                    placeholder="你是一位专业的短剧编剧，擅长…"
                    required
                  />
                </div>
                <div style={{ marginBottom: 14 }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                    <input type="checkbox" checked={presetForm.is_global} onChange={e => setPresetForm({ ...presetForm, is_global: e.target.checked })} />
                    全局预设（可在所有项目中使用）
                  </label>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="submit" className="btn btn-primary">保存</button>
                  <button type="button" className="btn btn-ghost" onClick={() => setShowPresetForm(false)}>取消</button>
                </div>
              </form>
            </div>
          )}

          {presets.length === 0 && !showPresetForm && (
            <div className="empty-state">
              <p>还没有提示词预设，点击「新增预设」创建编剧角色提示词</p>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {presets.map(p => (
              <div key={p.id} className="card">
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{p.name}</span>
                    <span className="badge" style={p.is_global ? { background: 'rgba(52,211,153,0.15)', color: '#34d399' } : {}}>
                      {p.is_global ? '全局' : '项目'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => handleEditPreset(p)}>编辑</button>
                    <button className="btn btn-danger" style={{ fontSize: 12 }} onClick={() => handleDeletePreset(p.id)}>删除</button>
                  </div>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-2)', whiteSpace: 'pre-wrap', maxHeight: 80, overflow: 'hidden' }}>{p.content}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
