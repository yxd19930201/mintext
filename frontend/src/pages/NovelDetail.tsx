import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useNovelStore } from '../stores/novelStore'
import { novelAiApi } from '../services/api/novelAiApi'
import { chapterApi } from '../services/api/chapterApi'
import { exportTxt } from '../utils/export'
import type { ChapterOutlineItem } from '../types/models'

export default function NovelDetail() {
  const { novelId } = useParams<{ novelId: string }>()
  const { currentNovel, chapters, loading, fetchNovel, fetchChapters, createChapter } = useNovelStore()
  const [outline, setOutline] = useState<ChapterOutlineItem[]>([])
  const [generating, setGenerating] = useState(false)
  const [totalChapters, setTotalChapters] = useState(50)
  const [showAiPanel, setShowAiPanel] = useState(false)
  const [batchGenerating, setBatchGenerating] = useState(false)
  const [selectedChapters, setSelectedChapters] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (novelId) {
      fetchNovel(Number(novelId))
      fetchChapters(Number(novelId))
    }
  }, [novelId, fetchNovel, fetchChapters])

  useEffect(() => {
    if (currentNovel?.outline) {
      try {
        const parsed = JSON.parse(currentNovel.outline)
        setOutline(parsed.chapters || [])
      } catch (e) {
        console.error('Failed to parse outline', e)
      }
    }
  }, [currentNovel])

  const handleGenerateOutline = async () => {
    if (!novelId || !currentNovel) return
    setGenerating(true)
    try {
      const res = await novelAiApi.generateOutline({
        novel_id: Number(novelId),
        total_chapters: totalChapters,
      })
      if (res.data) {
        setOutline(res.data.chapters)
        await fetchNovel(Number(novelId))
      }
    } catch (e) {
      alert('生成大纲失败: ' + String(e))
    } finally {
      setGenerating(false)
    }
  }

  const handleSyncToChapters = async () => {
    if (!novelId || outline.length === 0) return
    try {
      // 先拉取最新完整章节列表
      const latestRes = await chapterApi.list(Number(novelId))
      const latestChapters = latestRes.data || []

      // 删除大纲之外的多余章节
      for (const ch of latestChapters) {
        const inOutline = outline.find(o => o.chapter_number === ch.chapter_number)
        if (!inOutline) {
          await chapterApi.delete(Number(novelId), ch.id)
        }
      }

      // 按大纲逐章 upsert
      for (const item of outline) {
        const existing = latestChapters.find(c => c.chapter_number === item.chapter_number)
        if (existing) {
          await chapterApi.update(Number(novelId), existing.id, { title: item.title, synopsis: item.synopsis })
        } else {
          await createChapter(Number(novelId), {
            title: item.title,
            chapter_number: item.chapter_number,
            synopsis: item.synopsis,
          })
        }
      }

      await fetchChapters(Number(novelId))
      alert('同步成功！')
    } catch (e) {
      alert('同步失败: ' + String(e))
    }
  }

  const handleBatchGenerate = async (onlyMissing: boolean) => {
    if (!novelId) return
    setBatchGenerating(true)
    try {
      const res = await novelAiApi.batchGenerate(Number(novelId), { only_missing: onlyMissing })
      if (res.data) {
        alert(`批量生成完成！成功: ${res.data.succeeded}, 失败: ${res.data.failed}`)
        await fetchChapters(Number(novelId))
      }
    } catch (e) {
      alert('批量生成失败: ' + String(e))
    } finally {
      setBatchGenerating(false)
    }
  }

  const handleDeleteChapter = async (chapterId: number) => {
    if (!novelId || !confirm('确认删除该章节？')) return
    try {
      await chapterApi.delete(Number(novelId), chapterId)
      await fetchChapters(Number(novelId))
      setSelectedChapters(prev => { const s = new Set(prev); s.delete(chapterId); return s })
    } catch (e) {
      alert('删除失败: ' + String(e))
    }
  }

  const handleBatchDelete = async () => {
    if (!novelId || selectedChapters.size === 0 || !confirm(`确认删除选中的 ${selectedChapters.size} 个章节？`)) return
    setDeleting(true)
    try {
      for (const id of selectedChapters) {
        await chapterApi.delete(Number(novelId), id)
      }
      setSelectedChapters(new Set())
      await fetchChapters(Number(novelId))
    } catch (e) {
      alert('批量删除失败: ' + String(e))
    } finally {
      setDeleting(false)
    }
  }

  const handleGenerateNext = async () => {
    if (!novelId) return
    setGenerating(true)
    try {
      const res = await novelAiApi.generateNext(Number(novelId), {})
      if (res.data) {
        alert(`生成第 ${res.data.chapter_number} 章成功！`)
        await fetchChapters(Number(novelId))
      }
    } catch (e) {
      alert('生成下一章失败: ' + String(e))
    } finally {
      setGenerating(false)
    }
  }

  if (loading || !currentNovel) return <div>加载中...</div>

  return (
    <div style={{ maxWidth: 1000 }}>
      <div style={{ marginBottom: 24 }}>
        <Link to="/novels" style={{ color: '#666', textDecoration: 'none', fontSize: 14 }}>← 返回小说列表</Link>
      </div>

      <div style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h1 className="page-title">{currentNovel.title}</h1>
            {currentNovel.genre && <div style={{ color: '#666', marginBottom: 8 }}>{currentNovel.genre}</div>}
            <div style={{ color: '#888', lineHeight: 1.6 }}>{currentNovel.synopsis}</div>
          </div>
          <button
            className="btn btn-ghost"
            onClick={() => {
              const lines: string[] = [`【${currentNovel.title}】`]
              if (currentNovel.genre) lines.push(`类型：${currentNovel.genre}`)
              lines.push(``, `故事大概：${currentNovel.synopsis}`, ``)
              if (outline.length > 0) {
                lines.push(`=== 章节大纲 ===`, ``)
                outline.forEach(ch => {
                  lines.push(`第 ${ch.chapter_number} 章：${ch.title}`)
                  lines.push(ch.synopsis, ``)
                })
              } else if (chapters.length > 0) {
                lines.push(`=== 章节列表 ===`, ``)
                chapters.forEach(ch => {
                  lines.push(`第 ${ch.chapter_number} 章：${ch.title}`)
                  if (ch.synopsis) lines.push(ch.synopsis)
                  lines.push(``)
                })
              }
              exportTxt(lines.join('\n'), `${currentNovel.title}_大纲`)
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            导出大纲
          </button>
        </div>
      </div>

      {/* Outline Generation */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ fontWeight: 600, marginBottom: 16 }}>AI 生成大纲</div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginBottom: 16 }}>
          <div style={{ width: 150 }}>
            <label className="label">章节数</label>
            <input
              className="input"
              type="number"
              min={1}
              max={500}
              value={totalChapters}
              onChange={e => setTotalChapters(Number(e.target.value))}
            />
          </div>
          <button className="btn btn-primary" onClick={handleGenerateOutline} disabled={generating}>
            {generating ? '生成中...' : 'AI 生成大纲'}
          </button>
          {outline.length > 0 && (
            <button className="btn" onClick={handleSyncToChapters}>
              同步到章节 ({outline.length} 章)
            </button>
          )}
        </div>
        {outline.length > 0 && (
          <div style={{ maxHeight: 300, overflow: 'auto', border: '1px solid #e0e0e0', borderRadius: 6, padding: 12 }}>
            {outline.map(item => (
              <div key={item.chapter_number} style={{ marginBottom: 12, paddingBottom: 12, borderBottom: '1px solid #f0f0f0' }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>第 {item.chapter_number} 章：{item.title}</div>
                <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>{item.synopsis}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Chapters List */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ fontWeight: 600 }}>章节列表 ({chapters.length})</div>
            {chapters.length > 0 && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#666', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={selectedChapters.size === chapters.length && chapters.length > 0}
                  onChange={e => setSelectedChapters(e.target.checked ? new Set(chapters.map(c => c.id)) : new Set())}
                />
                全选
              </label>
            )}
            {selectedChapters.size > 0 && (
              <button className="btn btn-sm" style={{ color: '#ef4444', borderColor: '#ef4444' }} onClick={handleBatchDelete} disabled={deleting}>
                {deleting ? '删除中...' : `删除选中 (${selectedChapters.size})`}
              </button>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-sm" onClick={() => setShowAiPanel(!showAiPanel)}>
              AI 设置
            </button>
            <button className="btn btn-sm btn-primary" onClick={handleGenerateNext} disabled={generating || chapters.length === 0}>
              {generating ? '生成中...' : '继续生成下一章'}
            </button>
          </div>
        </div>

        {showAiPanel && (
          <div style={{ background: '#f8f8f8', padding: 16, borderRadius: 6, marginBottom: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 12, fontSize: 13 }}>批量生成</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-sm" onClick={() => handleBatchGenerate(false)} disabled={batchGenerating}>
                {batchGenerating ? '生成中...' : '一键生成所有章节'}
              </button>
              <button className="btn btn-sm" onClick={() => handleBatchGenerate(true)} disabled={batchGenerating}>
                {batchGenerating ? '生成中...' : '继续生成剩余'}
              </button>
            </div>
          </div>
        )}

        {chapters.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
            暂无章节，请先生成大纲并同步到章节
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {chapters.map(chapter => (
              <div key={chapter.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="checkbox"
                  checked={selectedChapters.has(chapter.id)}
                  onChange={e => setSelectedChapters(prev => {
                    const s = new Set(prev)
                    e.target.checked ? s.add(chapter.id) : s.delete(chapter.id)
                    return s
                  })}
                />
                <Link
                  to={`/novels/${novelId}/chapters/${chapter.id}`}
                  style={{ textDecoration: 'none', color: 'inherit', flex: 1 }}
                >
                  <div className="card" style={{ padding: 12, background: '#fafafa' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>第 {chapter.chapter_number} 章：{chapter.title}</div>
                        {chapter.synopsis && <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>{chapter.synopsis}</div>}
                      </div>
                    </div>
                  </div>
                </Link>
                <button
                  className="btn btn-sm"
                  style={{ color: '#ef4444', borderColor: '#ef4444', flexShrink: 0 }}
                  onClick={() => handleDeleteChapter(chapter.id)}
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
