import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { episodeApi } from '../services/api/episodeApi'
import { projectApi } from '../services/api/projectApi'
import { aiApi } from '../services/api/aiApi'
import { scriptApi } from '../services/api/scriptApi'
import { exportTxt } from '../utils/export'
import type { Episode, Project, OutlineEpisode, AIConfig, AIPromptPreset } from '../types/models'

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const id = Number(projectId)

  const [project, setProject] = useState<Project | null>(null)
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [loading, setLoading] = useState(true)
  const [title, setTitle] = useState('')
  const [showForm, setShowForm] = useState(false)

  const [outline, setOutline] = useState<{ total_episodes: number; theme: string; episodes: OutlineEpisode[] } | null>(null)
  const [generatingOutline, setGeneratingOutline] = useState(false)
  const [syncingEpisodes, setSyncingEpisodes] = useState(false)
  const [outlineTotalEpisodes, setOutlineTotalEpisodes] = useState(10)

  const [batchGenerating, setBatchGenerating] = useState(false)
  const [batchResult, setBatchResult] = useState<{ total: number; succeeded: number; failed: number } | null>(null)

  const [showAISettings, setShowAISettings] = useState(false)
  const [aiConfigs, setAIConfigs] = useState<AIConfig[]>([])
  const [presets, setPresets] = useState<AIPromptPreset[]>([])
  const [selectedConfigId, setSelectedConfigId] = useState<number | null>(null)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [savingSettings, setSavingSettings] = useState(false)

  useEffect(() => {
    Promise.all([projectApi.get(id), episodeApi.list(id)]).then(([projRes, epRes]) => {
      const proj = projRes.data!
      setProject(proj)
      setEpisodes(epRes.data)
      setSelectedConfigId(proj.ai_config_id)
      setSystemPrompt(proj.system_prompt ?? '')
      setOutlineTotalEpisodes(proj.total_episodes ?? 10)
      if (proj.outline) {
        try { setOutline(JSON.parse(proj.outline)) } catch { /* ignore */ }
      }
      setLoading(false)
    })
    aiApi.listConfigs().then(r => setAIConfigs(r.data ?? []))
    aiApi.listPresets().then(r => setPresets(r.data ?? []))
  }, [id])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    const res = await episodeApi.create(id, { title: title.trim(), episode_number: episodes.length + 1 })
    setEpisodes([...episodes, res.data!])
    setTitle('')
    setShowForm(false)
  }

  const handleGenerateOutline = async () => {
    setGeneratingOutline(true)
    try {
      const res = await aiApi.generateOutline(id, {
        total_episodes: outlineTotalEpisodes,
        ai_config_id: selectedConfigId ?? undefined,
        system_prompt: systemPrompt || undefined,
      })
      if (res.data) {
        setOutline(res.data)
        const projRes = await projectApi.get(id)
        setProject(projRes.data!)
      }
    } catch (e: any) {
      alert('生成大纲失败：' + (e?.response?.data?.detail ?? e?.message ?? '未知错误'))
    } finally {
      setGeneratingOutline(false)
    }
  }

  const handleSyncEpisodes = async () => {
    if (!outline) return
    setSyncingEpisodes(true)
    try {
      // 先拉取最新完整分集列表（不受旧缓存影响）
      const latestRes = await episodeApi.list(id)
      const latestEpisodes = latestRes.data

      // 删除大纲集数之外的多余分集
      for (const ep of latestEpisodes) {
        const inOutline = outline.episodes.find(o => o.episode_number === ep.episode_number)
        if (!inOutline) {
          await episodeApi.delete(id, ep.id)
        }
      }

      // 按大纲逐集 upsert
      for (const ep of outline.episodes) {
        const existing = latestEpisodes.find(e => e.episode_number === ep.episode_number)
        if (existing) {
          await episodeApi.update(id, existing.id, { title: ep.title, synopsis: ep.synopsis })
        } else {
          await episodeApi.create(id, { title: ep.title, episode_number: ep.episode_number, synopsis: ep.synopsis })
        }
      }

      const res = await episodeApi.list(id)
      setEpisodes(res.data)
    } finally {
      setSyncingEpisodes(false)
    }
  }

  const [generatingNext, setGeneratingNext] = useState(false)
  const [selectedEpisodes, setSelectedEpisodes] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)

  const handleDeleteEpisode = async (episodeId: number) => {
    if (!confirm('确认删除该分集？')) return
    try {
      await episodeApi.delete(id, episodeId)
      setEpisodes(prev => prev.filter(e => e.id !== episodeId))
      setSelectedEpisodes(prev => { const s = new Set(prev); s.delete(episodeId); return s })
    } catch (e: any) {
      alert('删除失败：' + (e?.response?.data?.detail ?? e?.message ?? '未知错误'))
    }
  }

  const handleBatchDelete = async () => {
    if (selectedEpisodes.size === 0 || !confirm(`确认删除选中的 ${selectedEpisodes.size} 个分集？`)) return
    setDeleting(true)
    try {
      for (const epId of selectedEpisodes) {
        await episodeApi.delete(id, epId)
      }
      setEpisodes(prev => prev.filter(e => !selectedEpisodes.has(e.id)))
      setSelectedEpisodes(new Set())
    } catch (e: any) {
      alert('批量删除失败：' + (e?.response?.data?.detail ?? e?.message ?? '未知错误'))
    } finally {
      setDeleting(false)
    }
  }

  const handleBatchExport = async () => {
    if (selectedEpisodes.size === 0) return
    setExporting(true)
    try {
      const selected = episodes.filter(ep => selectedEpisodes.has(ep.id))
        .sort((a, b) => a.episode_number - b.episode_number)
      const lines: string[] = [`【${project?.title ?? ''}】剧本导出`, '']
      for (const ep of selected) {
        const res = await scriptApi.list(ep.id)
        const scripts = res.data ?? []
        const latest = scripts[scripts.length - 1]
        lines.push(`${'='.repeat(40)}`)
        lines.push(`E${ep.episode_number} ${ep.title}`)
        if (ep.synopsis) lines.push(`简介：${ep.synopsis}`)
        lines.push('')
        lines.push(latest?.content?.trim() || '（暂无剧本内容）')
        lines.push('')
      }
      exportTxt(lines.join('\n'), `${project?.title ?? '项目'}_剧本`)
    } catch (e: any) {
      alert('导出失败：' + (e?.response?.data?.detail ?? e?.message ?? '未知错误'))
    } finally {
      setExporting(false)
    }
  }

  const handleGenerateNext = async () => {
    setGeneratingNext(true)
    try {
      const res = await aiApi.generateNextEpisode(id, {
        ai_config_id: selectedConfigId ?? undefined,
        system_prompt: systemPrompt || undefined,
      })
      if (res.data) {
        // 刷新分集列表
        const epRes = await episodeApi.list(id)
        setEpisodes(epRes.data)
      }
    } catch (e: any) {
      alert('生成失败：' + (e?.response?.data?.detail ?? e?.message ?? '未知错误'))
    } finally {
      setGeneratingNext(false)
    }
  }

  const handleBatchGenerate = async (onlyMissing = false) => {
    setBatchGenerating(true)
    setBatchResult(null)
    try {
      const res = await aiApi.batchGenerate(id, {
        ai_config_id: selectedConfigId ?? undefined,
        system_prompt: systemPrompt || undefined,
        only_missing: onlyMissing,
      })
      if (res.data) setBatchResult(res.data)
    } catch (e: any) {
      alert('批量生成失败：' + (e?.response?.data?.detail ?? e?.message ?? '未知错误'))
    } finally {
      setBatchGenerating(false)
    }
  }

  const handleSaveAISettings = async () => {
    setSavingSettings(true)
    try {
      const res = await projectApi.update(id, {
        ai_config_id: selectedConfigId,
        system_prompt: systemPrompt || null,
      })
      setProject(res.data!)
    } finally {
      setSavingSettings(false)
    }
  }

  return (
    <div style={{ maxWidth: 760 }}>
      <Link to="/" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-2)', fontSize: 13, marginBottom: 20, transition: 'color 0.15s' }}
        onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
        onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-2)')}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
        返回项目列表
      </Link>

      {loading ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-2)', padding: '40px 0' }}>
          <span className="spinner" /> 加载中…
        </div>
      ) : (
        <>
          {/* Block 1: Project info + outline */}
          <div className="card" style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
              <div>
                <h1 className="page-title" style={{ marginBottom: 4 }}>{project?.title}</h1>
                <div style={{ display: 'flex', gap: 6 }}>
                  {project?.genre && <span className="badge">{project.genre}</span>}
                  {project?.total_episodes && <span className="badge">{project.total_episodes} 集</span>}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <button
                  className="btn btn-ghost"
                  onClick={() => {
                    const lines: string[] = [`【${project?.title}】`, '']
                    if (project?.synopsis) lines.push(`故事梗概：${project.synopsis}`, '')
                    if (outline) {
                      lines.push(`大纲主题：${outline.theme}`, '')
                      outline.episodes.forEach(ep => {
                        lines.push(`E${ep.episode_number} ${ep.title}`)
                        lines.push(ep.synopsis, '')
                      })
                    } else {
                      episodes.forEach(ep => {
                        lines.push(`E${ep.episode_number} ${ep.title}`)
                        if (ep.synopsis) lines.push(ep.synopsis)
                        lines.push('')
                      })
                    }
                    exportTxt(lines.join('\n'), `${project?.title || '项目'}_大纲`)
                  }}
                  disabled={!project}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                  导出
                </button>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={200}
                  value={outlineTotalEpisodes}
                  onChange={e => setOutlineTotalEpisodes(Number(e.target.value))}
                  style={{ width: 72 }}
                  title="生成集数"
                />
                <span style={{ fontSize: 12, color: 'var(--text-3)' }}>集</span>
                <button
                  className="btn btn-primary"
                  onClick={handleGenerateOutline}
                  disabled={generatingOutline || !project?.synopsis}
                  title={!project?.synopsis ? '请先填写故事梗概' : ''}
                >
                  {generatingOutline ? <><span className="spinner" style={{ width: 13, height: 13 }} /> 生成中…</> : 'AI 生成大纲'}
                </button>
              </div>
            </div>

            {project?.synopsis && (
              <div style={{ fontSize: 13, color: 'var(--text-2)', marginBottom: 12, padding: '10px 12px', background: 'var(--bg-3)', borderRadius: 'var(--radius-sm)' }}>
                <span style={{ fontWeight: 600, color: 'var(--text-3)', fontSize: 11, display: 'block', marginBottom: 4 }}>故事梗概</span>
                {project.synopsis}
              </div>
            )}

            {outline && (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>大纲 · {outline.theme}</div>
                  <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={handleSyncEpisodes} disabled={syncingEpisodes}>
                    {syncingEpisodes ? <><span className="spinner" style={{ width: 12, height: 12 }} /> 同步中…</> : '同步到分集'}
                  </button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {outline.episodes.map(ep => (
                    <div key={ep.episode_number} style={{ display: 'flex', gap: 10, padding: '8px 10px', background: 'var(--bg-3)', borderRadius: 'var(--radius-sm)', fontSize: 13 }}>
                      <span style={{ color: 'var(--accent)', fontWeight: 700, flexShrink: 0, minWidth: 28 }}>E{ep.episode_number}</span>
                      <div>
                        <div style={{ fontWeight: 600, color: 'var(--text)' }}>{ep.title}</div>
                        <div style={{ color: 'var(--text-2)', fontSize: 12, marginTop: 2 }}>{ep.synopsis}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Block 2: Episode list */}
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>分集管理</h2>
                {episodes.length > 0 && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text-2)', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={selectedEpisodes.size === episodes.length && episodes.length > 0}
                      onChange={e => setSelectedEpisodes(e.target.checked ? new Set(episodes.map(ep => ep.id)) : new Set())}
                    />
                    全选
                  </label>
                )}
                {selectedEpisodes.size > 0 && (
                  <>
                    <button className="btn btn-ghost" style={{ fontSize: 12, color: 'var(--danger)', borderColor: 'var(--danger)' }} onClick={handleBatchDelete} disabled={deleting}>
                      {deleting ? '删除中…' : `删除选中 (${selectedEpisodes.size})`}
                    </button>
                    <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={handleBatchExport} disabled={exporting}>
                      {exporting
                        ? <><span className="spinner" style={{ width: 12, height: 12 }} /> 导出中…</>
                        : <><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>导出剧本 ({selectedEpisodes.size})</>
                      }
                    </button>
                  </>
                )}
              </div>
              <p className="page-subtitle">共 {episodes.length} 集</p>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                className="btn btn-ghost"
                onClick={handleGenerateNext}
                disabled={generatingNext}
                title="根据前集剧情，AI 自动生成下一集标题、简介和剧本"
              >
                {generatingNext
                  ? <><span className="spinner" style={{ width: 13, height: 13 }} /> 生成中…</>
                  : <><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 8v4l3 3"/><circle cx="18" cy="6" r="3"/></svg>继续生成下一集</>
                }
              </button>
              <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
                添加分集
              </button>
            </div>
          </div>

          {showForm && (
            <div className="card" style={{ marginBottom: 16 }}>
              <form onSubmit={handleCreate} style={{ display: 'flex', gap: 10 }}>
                <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder="分集标题" autoFocus />
                <button type="submit" className="btn btn-primary" style={{ flexShrink: 0 }}>创建</button>
                <button type="button" className="btn btn-ghost" style={{ flexShrink: 0 }} onClick={() => setShowForm(false)}>取消</button>
              </form>
            </div>
          )}

          {episodes.length === 0 && !showForm && (
            <div className="empty-state">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              <p>还没有分集，点击「添加分集」或先生成大纲再同步</p>
            </div>
          )}

          {episodes.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
              {episodes.map((ep) => (
                <div key={ep.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={selectedEpisodes.has(ep.id)}
                    onChange={e => setSelectedEpisodes(prev => {
                      const s = new Set(prev)
                      e.target.checked ? s.add(ep.id) : s.delete(ep.id)
                      return s
                    })}
                  />
                  <Link
                    to={`/projects/${id}/episodes/${ep.id}/script`}
                    className="card"
                    style={{ display: 'flex', alignItems: 'center', gap: 16, transition: 'border-color 0.15s', flex: 1 }}
                    onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
                    onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
                  >
                    <div style={{
                      width: 40, height: 40, borderRadius: 8, flexShrink: 0,
                      background: 'var(--bg-3)', border: '1px solid var(--border)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontWeight: 700, fontSize: 13, color: 'var(--accent)',
                    }}>
                      {ep.episode_number}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)' }}>{ep.title}</div>
                      {ep.synopsis && <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>{ep.synopsis}</div>}
                    </div>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ color: 'var(--text-3)' }}><path d="M9 18l6-6-6-6"/></svg>
                  </Link>
                  <button
                    className="btn btn-ghost"
                    style={{ fontSize: 12, color: 'var(--danger)', borderColor: 'var(--danger)', flexShrink: 0 }}
                    onClick={() => handleDeleteEpisode(ep.id)}
                  >
                    删除
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Block 3: Batch generate + AI settings */}
          <div className="card">
            <button
              style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text)', fontWeight: 600, fontSize: 14, padding: 0, width: '100%' }}
              onClick={() => setShowAISettings(!showAISettings)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></svg>
              AI 生成设置
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ marginLeft: 'auto', transform: showAISettings ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}><path d="M6 9l6 6 6-6"/></svg>
            </button>

            {showAISettings && (
              <div style={{ marginTop: 16 }}>
                <div style={{ marginBottom: 12 }}>
                  <label className="label">AI 配置</label>
                  <select
                    className="input"
                    value={selectedConfigId ?? ''}
                    onChange={e => setSelectedConfigId(e.target.value ? Number(e.target.value) : null)}
                  >
                    <option value="">使用全局默认</option>
                    {aiConfigs.map(c => (
                      <option key={c.id} value={c.id}>{c.name} ({c.model})</option>
                    ))}
                  </select>
                </div>
                <div style={{ marginBottom: 12 }}>
                  <label className="label">系统提示词（覆盖全局）</label>
                  <select
                    className="input"
                    style={{ marginBottom: 8 }}
                    onChange={e => { if (e.target.value) setSystemPrompt(e.target.value) }}
                    defaultValue=""
                  >
                    <option value="">选择预设…</option>
                    {presets.map(p => (
                      <option key={p.id} value={p.content}>{p.name}</option>
                    ))}
                  </select>
                  <textarea
                    className="textarea"
                    value={systemPrompt}
                    onChange={e => setSystemPrompt(e.target.value)}
                    rows={4}
                    placeholder="留空则使用默认编剧提示词…"
                  />
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button className="btn btn-ghost" onClick={handleSaveAISettings} disabled={savingSettings}>
                    {savingSettings ? '保存中…' : '保存设置'}
                  </button>
                  <button
                    className="btn btn-ghost"
                    onClick={() => handleBatchGenerate(true)}
                    disabled={batchGenerating || episodes.length === 0}
                    title="只生成尚未有剧本的集，并与上一集情节衔接"
                  >
                    {batchGenerating ? <><span className="spinner" style={{ width: 13, height: 13 }} /> 生成中…</> : '继续生成剩余'}
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={() => handleBatchGenerate(false)}
                    disabled={batchGenerating || episodes.length === 0}
                  >
                    {batchGenerating ? <><span className="spinner" style={{ width: 13, height: 13 }} /> 生成中…</> : '一键生成所有剧本'}
                  </button>
                </div>
                {batchResult && (
                  <div style={{ marginTop: 10, fontSize: 13, color: 'var(--text-2)' }}>
                    完成：共 {batchResult.total} 集，成功 <span style={{ color: '#34d399' }}>{batchResult.succeeded}</span>，失败 <span style={{ color: 'var(--danger)' }}>{batchResult.failed}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
