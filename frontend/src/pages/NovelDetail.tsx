import { useEffect, useState, useRef } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useNovelStore } from '../stores/novelStore'
import { novelAiApi } from '../services/api/novelAiApi'
import type { KnowledgeGraph } from '../services/api/novelAiApi'
import { novelApi } from '../services/api/novelApi'
import { chapterApi } from '../services/api/chapterApi'
import { exportTxt } from '../utils/export'
import type { ChapterOutlineItem } from '../types/models'

export default function NovelDetail() {
  const { novelId } = useParams<{ novelId: string }>()
  const { currentNovel, chapters, loading, fetchNovel, fetchChapters, createChapter } = useNovelStore()
  const [outline, setOutline] = useState<ChapterOutlineItem[]>([])
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<ChapterOutlineItem | null>(null)
  const [savingOutline, setSavingOutline] = useState(false)
  const [syncingIndex, setSyncingIndex] = useState<number | null>(null)
  const [generating, setGenerating] = useState(false)
  const [totalChapters, setTotalChapters] = useState(50)
  const [showAiPanel, setShowAiPanel] = useState(false)
  const [batchGenerating, setBatchGenerating] = useState(false)
  const [selectedChapters, setSelectedChapters] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  const [graph, setGraph] = useState<KnowledgeGraph | null>(null)
  const [showGraph, setShowGraph] = useState(false)
  const [graphLoading, setGraphLoading] = useState(false)
  const [rebuildingGraph, setRebuildingGraph] = useState(false)
  const [rebuildProgress, setRebuildProgress] = useState<{ done: number; total: number } | null>(null)

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

  const [generatingProgress, setGeneratingProgress] = useState<{ done: number; total: number } | null>(null)

  const handleGenerateOutline = async () => {
    if (!novelId || !currentNovel) return
    setGenerating(true)
    setOutline([])
    setGeneratingProgress({ done: 0, total: totalChapters })

    const BATCH = 5
    let accumulated: ChapterOutlineItem[] = []

    try {
      // First batch to get the theme
      const firstEnd = Math.min(BATCH, totalChapters)
      const firstRes = await novelAiApi.generateOutline({
        novel_id: Number(novelId),
        total_chapters: totalChapters,
        start_chapter: 1,
        end_chapter: firstEnd,
      })
      const theme = firstRes.data?.theme || ''
      accumulated = [...(firstRes.data?.chapters || [])]
      setOutline([...accumulated])
      setGeneratingProgress({ done: firstEnd, total: totalChapters })

      // Remaining batches in parallel groups of 4
      const remaining: Array<{ start: number; end: number }> = []
      for (let start = firstEnd + 1; start <= totalChapters; start += BATCH) {
        remaining.push({ start, end: Math.min(start + BATCH - 1, totalChapters) })
      }

      const CONCURRENCY = 4
      for (let i = 0; i < remaining.length; i += CONCURRENCY) {
        const group = remaining.slice(i, i + CONCURRENCY)
        const results = await Promise.all(
          group.map(({ start, end }) =>
            novelAiApi.generateOutline({
              novel_id: Number(novelId),
              total_chapters: totalChapters,
              start_chapter: start,
              end_chapter: end,
              theme,
            })
          )
        )
        for (const res of results) {
          if (res.data?.chapters) accumulated.push(...res.data.chapters)
        }
        accumulated.sort((a, b) => a.chapter_number - b.chapter_number)
        setOutline([...accumulated])
        const lastDone = group[group.length - 1].end
        setGeneratingProgress({ done: lastDone, total: totalChapters })
      }

      await fetchNovel(Number(novelId))
    } catch (e) {
      alert('生成大纲失败: ' + String(e))
    } finally {
      setGenerating(false)
      setGeneratingProgress(null)
    }
  }

  const handleSaveOutlineEdit = async () => {
    if (editingIndex === null || !editDraft || !novelId || !currentNovel) return
    const updated = outline.map((item, i) => i === editingIndex ? editDraft : item)
    setSavingOutline(true)
    try {
      const outlineJson = JSON.stringify({
        total_chapters: updated.length,
        theme: currentNovel.outline ? (JSON.parse(currentNovel.outline).theme || '') : '',
        chapters: updated,
      })
      await novelApi.update(Number(novelId), { outline: outlineJson })
      setOutline(updated)
      setEditingIndex(null)
      setEditDraft(null)
    } catch (e) {
      alert('保存失败: ' + String(e))
    } finally {
      setSavingOutline(false)
    }
  }

  const handleSyncSingleChapter = async (item: ChapterOutlineItem) => {
    if (!novelId) return
    setSyncingIndex(item.chapter_number)
    try {
      const latestRes = await chapterApi.list(Number(novelId))
      const existing = (latestRes.data || []).find(c => c.chapter_number === item.chapter_number)
      if (existing) {
        await chapterApi.update(Number(novelId), existing.id, { title: item.title, synopsis: item.synopsis })
      } else {
        await createChapter(Number(novelId), {
          title: item.title,
          chapter_number: item.chapter_number,
          synopsis: item.synopsis,
        })
      }
      await fetchChapters(Number(novelId))
    } catch (e) {
      alert('同步失败: ' + String(e))
    } finally {
      setSyncingIndex(null)
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

  const handleLoadGraph = async () => {
    if (!novelId) return
    setGraphLoading(true)
    try {
      const res = await novelAiApi.getGraph(Number(novelId))
      const raw = res.data || {}
      setGraph({ characters: raw.characters || [], events: raw.events || [] })
      setShowGraph(true)
    } catch (e) {
      alert('加载图谱失败: ' + String(e))
    } finally {
      setGraphLoading(false)
    }
  }

  const handleRebuildGraph = async () => {
    if (!novelId || !confirm('将重新分析所有已生成章节内容来重建图谱，可能需要几分钟，确认继续？')) return
    setRebuildingGraph(true)
    setRebuildProgress(null)
    try {
      await novelAiApi.clearGraph(Number(novelId))
      setGraph({ characters: [], events: [] })

      const chaptersRes = await novelAiApi.getChaptersWithContent(Number(novelId))
      const chapters = chaptersRes.data || []
      if (chapters.length === 0) {
        alert('没有已生成内容的章节')
        return
      }

      setRebuildProgress({ done: 0, total: chapters.length })

      for (let i = 0; i < chapters.length; i++) {
        const ch = chapters[i]
        try {
          const res = await novelAiApi.updateGraphFromChapter(Number(novelId), ch.id)
          if (res.data) {
            setGraph({ characters: res.data.characters || [], events: res.data.events || [] })
          }
          setRebuildProgress({ done: i + 1, total: chapters.length })
        } catch (e) {
          console.error(`Failed to update graph for chapter ${ch.chapter_number}:`, e)
        }
      }

      setShowGraph(true)
      alert('图谱重建完成！')
    } catch (e) {
      alert('重建图谱失败: ' + String(e))
    } finally {
      setRebuildingGraph(false)
      setRebuildProgress(null)
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
            {generating
              ? generatingProgress
                ? `生成中 ${generatingProgress.done}/${generatingProgress.total}...`
                : '生成中...'
              : 'AI 生成大纲'}
          </button>
          {outline.length > 0 && (
            <button className="btn" onClick={handleSyncToChapters}>
              同步到章节 ({outline.length} 章)
            </button>
          )}
        </div>
        {outline.length > 0 && (
          <div style={{ maxHeight: 400, overflow: 'auto', border: '1px solid #e0e0e0', borderRadius: 6, padding: 12 }}>
            {outline.map((item, i) => (
              <div key={item.chapter_number} style={{ marginBottom: 12, paddingBottom: 12, borderBottom: '1px solid #f0f0f0' }}>
                {editingIndex === i ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <input
                      className="input"
                      style={{ fontSize: 13, fontWeight: 600 }}
                      value={editDraft?.title || ''}
                      onChange={e => setEditDraft(d => d ? { ...d, title: e.target.value } : d)}
                    />
                    <textarea
                      className="textarea"
                      style={{ fontSize: 12, minHeight: 60 }}
                      value={editDraft?.synopsis || ''}
                      onChange={e => setEditDraft(d => d ? { ...d, synopsis: e.target.value } : d)}
                    />
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button className="btn btn-primary btn-sm" onClick={handleSaveOutlineEdit} disabled={savingOutline}>
                        {savingOutline ? '保存中...' : '保存'}
                      </button>
                      <button className="btn btn-sm" onClick={() => { setEditingIndex(null); setEditDraft(null) }}>取消</button>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>第 {item.chapter_number} 章：{item.title}</div>
                      <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>{item.synopsis}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                      <button
                        className="btn btn-sm"
                        style={{ fontSize: 11 }}
                        onClick={() => { setEditingIndex(i); setEditDraft({ ...item }) }}
                      >编辑</button>
                      <button
                        className="btn btn-sm"
                        style={{ fontSize: 11 }}
                        onClick={() => handleSyncSingleChapter(item)}
                        disabled={syncingIndex === item.chapter_number}
                      >
                        {syncingIndex === item.chapter_number ? '同步中...' : '同步'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Knowledge Graph */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontWeight: 600 }}>图谱（人物关系 & 事件）</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-sm" onClick={handleLoadGraph} disabled={graphLoading}>
              {graphLoading ? '加载中...' : showGraph ? '刷新' : '查看图谱'}
            </button>
            <button className="btn btn-sm" onClick={handleRebuildGraph} disabled={rebuildingGraph}>
              {rebuildingGraph
                ? rebuildProgress
                  ? `分析中 ${rebuildProgress.done}/${rebuildProgress.total}...`
                  : '准备中...'
                : '重新分析'}
            </button>
          </div>
        </div>

        {showGraph && graph && (
          <div style={{ marginTop: 16 }}>
            {/* Characters */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: '#555' }}>
                人物关系 ({graph.characters.length})
              </div>
              {graph.characters.length === 0 ? (
                <div style={{ color: '#999', fontSize: 13 }}>暂无人物数据</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {graph.characters.map((char, i) => (
                    <div key={i} style={{ background: '#f8f8f8', borderRadius: 6, padding: '10px 12px', fontSize: 13 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ fontWeight: 700, color: '#1a1a1a' }}>{char.name}</span>
                        <span style={{ fontSize: 11, color: '#888', background: '#e8e8e8', borderRadius: 4, padding: '1px 6px' }}>{char.role}</span>
                      </div>
                      {char.description && <div style={{ color: '#555', marginBottom: 4 }}>{char.description}</div>}
                      {(char.relations || []).length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {(char.relations || []).map((r, j) => (
                            <span key={j} style={{ fontSize: 11, color: '#666', background: '#efefef', borderRadius: 4, padding: '2px 6px' }}>
                              {r.target} · {r.relation}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Events */}
            <div>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: '#555' }}>
                关键事件 ({graph.events.length})
              </div>
              {graph.events.length === 0 ? (
                <div style={{ color: '#999', fontSize: 13 }}>暂无事件数据</div>
              ) : (
                <div style={{ maxHeight: 300, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {graph.events.map((ev, i) => (
                    <div key={i} style={{ background: '#f8f8f8', borderRadius: 6, padding: '8px 12px', fontSize: 13 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                        <span style={{ fontSize: 11, color: '#888', background: '#e8e8e8', borderRadius: 4, padding: '1px 6px' }}>第{ev.chapter}章</span>
                        <span style={{ fontWeight: 600 }}>{ev.title}</span>
                      </div>
                      <div style={{ color: '#555' }}>{ev.description}</div>
                      {(ev.related_characters || []).length > 0 && (
                        <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {(ev.related_characters || []).map((c, j) => (
                            <span key={j} style={{ fontSize: 11, color: '#666', background: '#efefef', borderRadius: 4, padding: '1px 6px' }}>{c}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
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
