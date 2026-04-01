import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useProjectStore } from '../stores/projectStore'

export default function ProjectList() {
  const { projects, loading, error, fetchProjects, createProject, deleteProject } = useProjectStore()
  const [title, setTitle] = useState('')
  const [genre, setGenre] = useState('')
  const [synopsis, setSynopsis] = useState('')
  const [totalEpisodes, setTotalEpisodes] = useState(10)
  const [showForm, setShowForm] = useState(false)

  useEffect(() => { fetchProjects() }, [fetchProjects])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    await createProject({
      title: title.trim(),
      genre: genre.trim() || undefined,
      synopsis: synopsis.trim() || undefined,
      total_episodes: totalEpisodes,
    })
    setTitle('')
    setGenre('')
    setSynopsis('')
    setTotalEpisodes(10)
    setShowForm(false)
  }

  return (
    <div style={{ maxWidth: 860 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 className="page-title">我的项目</h1>
          <p className="page-subtitle">管理你的短剧剧本项目</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
          新建项目
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ fontWeight: 600, marginBottom: 16, fontSize: 14 }}>新建项目</div>
          <form onSubmit={handleCreate}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: 12, marginBottom: 12 }}>
              <div>
                <label className="label">项目名称</label>
                <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder="例：都市爱情短剧" autoFocus />
              </div>
              <div>
                <label className="label">类型（可选）</label>
                <input className="input" value={genre} onChange={e => setGenre(e.target.value)} placeholder="例：爱情 / 悬疑" />
              </div>
            </div>
            <div style={{ marginBottom: 12 }}>
              <label className="label">故事梗概（可选，用于 AI 生成大纲）</label>
              <textarea
                className="textarea"
                value={synopsis}
                onChange={e => setSynopsis(e.target.value)}
                rows={3}
                placeholder="简述故事背景、主要人物和核心冲突，AI 将根据此生成分集大纲…"
              />
            </div>
            <div style={{ marginBottom: 14, maxWidth: 200 }}>
              <label className="label">计划集数</label>
              <input
                className="input"
                type="number"
                min={1}
                max={200}
                value={totalEpisodes}
                onChange={e => setTotalEpisodes(Number(e.target.value))}
              />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" className="btn btn-primary">创建</button>
              <button type="button" className="btn btn-ghost" onClick={() => setShowForm(false)}>取消</button>
            </div>
          </form>
        </div>
      )}

      {/* States */}
      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-2)', padding: '40px 0' }}>
          <span className="spinner" /> 加载中…
        </div>
      )}
      {error && (
        <div style={{ background: 'rgba(248,113,113,0.1)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-sm)', padding: '12px 16px', color: 'var(--danger)', fontSize: 13 }}>
          {error}
        </div>
      )}

      {/* Project grid */}
      {!loading && !error && projects.length === 0 && !showForm && (
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
          <p>还没有项目，点击「新建项目」开始创作</p>
        </div>
      )}

      {!loading && projects.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}>
          {projects.map((p) => (
            <div key={p.id} className="card" style={{ position: 'relative', transition: 'border-color 0.15s', cursor: 'default' }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 8,
                  background: `hsl(${(p.id * 47) % 360}, 60%, 25%)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 16, fontWeight: 700, color: `hsl(${(p.id * 47) % 360}, 80%, 75%)`,
                }}>
                  {p.title[0]}
                </div>
                <button className="btn btn-danger" style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => deleteProject(p.id)}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>
                </button>
              </div>
              <Link to={`/projects/${p.id}`} style={{ display: 'block' }}>
                <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4, color: 'var(--text)' }}>{p.title}</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
                  {p.genre && <span className="badge">{p.genre}</span>}
                  {p.total_episodes && <span className="badge">{p.total_episodes} 集</span>}
                  {!p.genre && !p.total_episodes && <span style={{ fontSize: 12, color: 'var(--text-3)' }}>未设置类型</span>}
                </div>
                {p.synopsis && (
                  <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                    {p.synopsis}
                  </div>
                )}
                <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-3)' }}>
                  {new Date(p.created_at).toLocaleDateString('zh-CN')}
                </div>
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
