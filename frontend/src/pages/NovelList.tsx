import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useNovelStore } from '../stores/novelStore'

export default function NovelList() {
  const { novels, loading, error, fetchNovels, createNovel, deleteNovel } = useNovelStore()
  const [title, setTitle] = useState('')
  const [genre, setGenre] = useState('')
  const [synopsis, setSynopsis] = useState('')
  const [totalChapters, setTotalChapters] = useState(50)
  const [showForm, setShowForm] = useState(false)

  useEffect(() => { fetchNovels() }, [fetchNovels])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !synopsis.trim()) return
    await createNovel({
      title: title.trim(),
      genre: genre.trim() || undefined,
      synopsis: synopsis.trim(),
      total_chapters: totalChapters,
    })
    setTitle('')
    setGenre('')
    setSynopsis('')
    setTotalChapters(50)
    setShowForm(false)
  }

  return (
    <div style={{ maxWidth: 860 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 className="page-title">我的小说</h1>
          <p className="page-subtitle">管理你的小说创作项目</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M12 5v14M5 12h14"/></svg>
          新建小说
        </button>
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ fontWeight: 600, marginBottom: 16, fontSize: 14 }}>新建小说</div>
          <form onSubmit={handleCreate}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: 12, marginBottom: 12 }}>
              <div>
                <label className="label">小说名称</label>
                <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder="例：修仙传奇" autoFocus />
              </div>
              <div>
                <label className="label">类型（可选）</label>
                <input className="input" value={genre} onChange={e => setGenre(e.target.value)} placeholder="例：玄幻 / 都市" />
              </div>
            </div>
            <div style={{ marginBottom: 12 }}>
              <label className="label">故事大概（必填，用于 AI 生成大纲）</label>
              <textarea
                className="textarea"
                value={synopsis}
                onChange={e => setSynopsis(e.target.value)}
                rows={4}
                placeholder="简述故事背景、主要人物和核心情节，AI 将根据此生成章节大纲…"
                required
              />
            </div>
            <div style={{ marginBottom: 14, maxWidth: 200 }}>
              <label className="label">计划章节数</label>
              <input
                className="input"
                type="number"
                min={1}
                max={500}
                value={totalChapters}
                onChange={e => setTotalChapters(Number(e.target.value))}
              />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" className="btn btn-primary">创建</button>
              <button type="button" className="btn" onClick={() => setShowForm(false)}>取消</button>
            </div>
          </form>
        </div>
      )}

      {loading && <div>加载中...</div>}
      {error && <div style={{ color: 'red' }}>错误: {error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
        {novels.map(novel => (
          <div key={novel.id} className="card" style={{ position: 'relative' }}>
            <Link to={`/novels/${novel.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
              <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 15 }}>{novel.title}</div>
              {novel.genre && <div style={{ fontSize: 12, color: '#666', marginBottom: 8 }}>{novel.genre}</div>}
              <div style={{ fontSize: 13, color: '#888', marginBottom: 12, lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                {novel.synopsis}
              </div>
              <div style={{ fontSize: 12, color: '#999' }}>
                {novel.total_chapters ? `计划 ${novel.total_chapters} 章` : '未设置章节数'}
              </div>
            </Link>
            <button
              className="btn btn-sm"
              style={{ position: 'absolute', top: 12, right: 12, padding: '4px 8px' }}
              onClick={(e) => {
                e.preventDefault()
                if (confirm(`确定删除小说「${novel.title}」吗？`)) {
                  deleteNovel(novel.id)
                }
              }}
            >
              删除
            </button>
          </div>
        ))}
      </div>

      {!loading && novels.length === 0 && (
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
          暂无小说项目，点击「新建小说」开始创作
        </div>
      )}
    </div>
  )
}
