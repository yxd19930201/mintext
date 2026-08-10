import { useEffect, useState } from 'react'
import { aiApi } from '../services/api/aiApi'
import type { AIConfig } from '../types/models'

const emptyConfig = {
  name: '',
  base_url: '',
  api_key: '',
  model: '',
  is_default: false,
  input_price_cny: 0,
  output_price_cny: 0,
}

export default function Settings() {
  // AI Configs
  const [configs, setConfigs] = useState<AIConfig[]>([])
  const [configForm, setConfigForm] = useState(emptyConfig)
  const [editingConfig, setEditingConfig] = useState<AIConfig | null>(null)
  const [showConfigForm, setShowConfigForm] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [generationMode, setGenerationMode] = useState(
    localStorage.getItem('mintext:generationMode') || 'economy',
  )
  const [usage, setUsage] = useState<any>(null)

  useEffect(() => {
    aiApi.listConfigs().then(r => setConfigs(r.data ?? []))
    aiApi.getUsage().then(r => setUsage(r.data))
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
    setConfigForm({
      name: c.name,
      base_url: c.base_url,
      api_key: c.api_key,
      model: c.model,
      is_default: c.is_default,
      input_price_cny: c.input_price_cny || 0,
      output_price_cny: c.output_price_cny || 0,
    })
    setShowConfigForm(true)
  }

  const handleDeleteConfig = async (id: number) => {
    if (!confirm('确认删除此 AI 配置？')) return
    await aiApi.deleteConfig(id)
    setConfigs(configs.filter(c => c.id !== id))
  }

  return (
    <div style={{ maxWidth: 760 }}>
      <h1 className="page-title">设置</h1>
      <p className="page-subtitle" style={{ marginBottom: 24 }}>管理 AI 模型接口和默认模型</p>

      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ fontWeight: 600, marginBottom: 12 }}>生成模式</div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            className={`btn ${generationMode === 'economy' ? 'btn-primary' : ''}`}
            onClick={() => {
              setGenerationMode('economy')
              localStorage.setItem('mintext:generationMode', 'economy')
            }}
          >
            经济
          </button>
          <button
            className={`btn ${generationMode === 'strict' ? 'btn-primary' : ''}`}
            onClick={() => {
              setGenerationMode('strict')
              localStorage.setItem('mintext:generationMode', 'strict')
            }}
          >
            标准
          </button>
        </div>
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-2)', lineHeight: 1.6 }}>
          {generationMode === 'economy'
            ? '大纲每批调用1次，正文每章调用1次；不执行额外AI审核和自动返修，人物、资产及不可逆事实根据大纲状态在本地更新。速度更快、消耗更低，适合初稿和批量生成。'
            : '大纲和正文生成后都会执行AI一致性审核；发现冲突时自动返修并重新审核，正文通过后再由AI提取人物、资产及不可逆事实。连续性更严格，适合重要长篇和定稿。'}
          <div style={{ marginTop: 4, color: 'var(--text-3)' }}>
            经济模式通常只产生基础生成调用；标准模式会增加审核、返修和账本提取调用，实际Token消耗取决于章节长度及返修次数。
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontWeight: 600 }}>Token与费用统计</div>
          <button
            className="btn btn-ghost"
            onClick={async () => {
              if (!confirm('确认清空Token与费用统计？')) return
              await aiApi.resetUsage()
              const res = await aiApi.getUsage()
              setUsage(res.data)
            }}
          >
            清空统计
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginTop: 14 }}>
          <div><div className="label">调用次数</div><b>{usage?.calls || 0}</b></div>
          <div><div className="label">输入Token</div><b>{(usage?.prompt_tokens || 0).toLocaleString()}</b></div>
          <div><div className="label">输出Token</div><b>{(usage?.completion_tokens || 0).toLocaleString()}</b></div>
          <div><div className="label">预估费用</div><b>¥{Number(usage?.estimated_cost_cny || 0).toFixed(4)}</b></div>
        </div>
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-3)' }}>
          费用依据下方AI配置中的每百万Token价格估算；未填写价格时只统计Token。
        </div>
      </div>

      {/* Tab: AI Configs */}
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
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
                  <div>
                    <label className="label">输入价格（元/百万Token）</label>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step="0.0001"
                      value={configForm.input_price_cny}
                      onChange={e => setConfigForm({ ...configForm, input_price_cny: Number(e.target.value) || 0 })}
                    />
                  </div>
                  <div>
                    <label className="label">输出价格（元/百万Token）</label>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      step="0.0001"
                      value={configForm.output_price_cny}
                      onChange={e => setConfigForm({ ...configForm, output_price_cny: Number(e.target.value) || 0 })}
                    />
                  </div>
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
                    {c.is_default && <span className="badge">默认</span>}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>{c.base_url} · {c.model}</div>
                </div>
                <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => handleEditConfig(c)}>编辑</button>
                <button className="btn btn-danger" style={{ fontSize: 12 }} onClick={() => handleDeleteConfig(c.id)}>删除</button>
              </div>
            ))}
          </div>
      </div>
    </div>
  )
}
