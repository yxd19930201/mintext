import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useNovelStore } from '../stores/novelStore'
import { novelAiApi } from '../services/api/novelAiApi'
import type { CanonArchive } from '../services/api/novelAiApi'
import { novelApi } from '../services/api/novelApi'
import { chapterApi } from '../services/api/chapterApi'
import { exportTxt } from '../utils/export'
import type { ChapterOutlineItem } from '../types/models'
import { usePersistentState } from '../stores/persistentTaskStore'
import CanonArchivePanel from '../components/CanonArchivePanel'

export default function NovelDetail() {
  const { novelId } = useParams<{ novelId: string }>()
  const { currentNovel, chapters, loading, fetchNovel, fetchChapters, createChapter } = useNovelStore()
  const [outline, setOutline] = usePersistentState<ChapterOutlineItem[]>(`novel:${novelId}:outline`, [])
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<ChapterOutlineItem | null>(null)
  const [savingOutline, setSavingOutline] = useState(false)
  const [syncingIndex, setSyncingIndex] = useState<number | null>(null)
  const [syncingAll, setSyncingAll] = usePersistentState(`novel:${novelId}:syncingAll`, false)
  const [syncProgress, setSyncProgress] = usePersistentState<{ done: number; total: number } | null>(`novel:${novelId}:syncProgress`, null)
  const [generating, setGenerating] = usePersistentState(`novel:${novelId}:generating`, false)
  const [totalChapters, setTotalChapters] = useState(50)
  const [selectedChapters, setSelectedChapters] = useState<Set<number>>(new Set())
  const [deleting, setDeleting] = useState(false)

  const [graph, setGraph] = usePersistentState<CanonArchive | null>(`novel:${novelId}:graph`, null)
  const [showGraph, setShowGraph] = useState(false)
  const [graphLoading, setGraphLoading] = useState(false)
  const [rebuildingGraph, setRebuildingGraph] = usePersistentState(`novel:${novelId}:rebuildingGraph`, false)
  const [rebuildProgress, setRebuildProgress] = usePersistentState<{ done: number; total: number } | null>(`novel:${novelId}:rebuildProgress`, null)

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

  useEffect(() => {
    if (currentNovel?.total_chapters) {
      setTotalChapters(currentNovel.total_chapters)
    }
  }, [currentNovel?.total_chapters])

  const [generatingProgress, setGeneratingProgress] = usePersistentState<{ done: number; total: number } | null>(`novel:${novelId}:generatingProgress`, null)

  const handleGenerateOutline = async () => {
    if (!novelId || !currentNovel) return
    if (!Number.isInteger(totalChapters) || totalChapters < 1 || totalChapters > 200) {
      alert('章节数必须是 1–200 之间的整数')
      return
    }
    const BATCH = 5
    let storedOutlineData: any = null
    if (currentNovel.outline) {
      try {
        storedOutlineData = JSON.parse(currentNovel.outline)
      } catch {
        // Fall back to the already rendered outline when legacy JSON is malformed.
      }
    }
    const authoritativeOutline: ChapterOutlineItem[] =
      Array.isArray(storedOutlineData?.chapters) ? storedOutlineData.chapters : outline
    const existingByNumber = new Map(
      authoritativeOutline
        .filter(item => item.chapter_number >= 1 && item.chapter_number <= totalChapters)
        .map(item => [item.chapter_number, item]),
    )
    let accumulated = Array.from(existingByNumber.values())
      .sort((a, b) => a.chapter_number - b.chapter_number)
    const missingNumbers = Array.from(
      { length: totalChapters },
      (_, index) => index + 1,
    ).filter(chapterNumber => !existingByNumber.has(chapterNumber))

    if (missingNumbers.length === 0) {
      alert(`大纲已完整生成，共 ${totalChapters} 章，无需重复生成。`)
      return
    }

    // Group only missing consecutive chapters, at most five per request.
    // This makes the operation resumable after a network/provider failure.
    const remaining: Array<{ start: number; end: number }> = []
    for (const chapterNumber of missingNumbers) {
      const current = remaining[remaining.length - 1]
      if (
        current
        && chapterNumber === current.end + 1
        && current.end - current.start + 1 < BATCH
      ) {
        current.end = chapterNumber
      } else {
        remaining.push({ start: chapterNumber, end: chapterNumber })
      }
    }

    let theme = storedOutlineData?.theme || ''

    setGenerating(true)
    setOutline([...accumulated])
    setGeneratingProgress({
      done: totalChapters - missingNumbers.length,
      total: totalChapters,
    })

    try {
      // Serialize persistence batches. Concurrent requests used to read the
      // same old outline and overwrite one another (50 chapters could become 25).
      let generatedCount = 0
      for (const { start, end } of remaining) {
        const res = await novelAiApi.generateOutline({
          novel_id: Number(novelId),
          total_chapters: totalChapters,
          start_chapter: start,
          end_chapter: end,
          theme,
        })
        if (!theme && res.data?.theme) {
          theme = res.data.theme
        }
        if (res.data?.chapters) {
          const merged = new Map(
            accumulated.map(item => [item.chapter_number, item]),
          )
          for (const item of res.data.chapters) {
            merged.set(item.chapter_number, item)
          }
          accumulated = Array.from(merged.values())
            .sort((a, b) => a.chapter_number - b.chapter_number)
        }
        setOutline([...accumulated])
        generatedCount += end - start + 1
        setGeneratingProgress({
          done: totalChapters - missingNumbers.length + generatedCount,
          total: totalChapters,
        })
      }

      // The backend is authoritative: every serialized batch has already been
      // reviewed and transactionally merged with its Skill metadata. Do not
      // overwrite it here with a reduced client-side shape.
      const completeOutline = Array.from(
        new Map(accumulated.map(item => [item.chapter_number, item])).values(),
      ).sort((a, b) => a.chapter_number - b.chapter_number)
      setOutline(completeOutline)
      await fetchNovel(Number(novelId))
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const message = typeof detail === 'string'
        ? detail
        : detail?.message
          ? `${detail.message}${Array.isArray(detail.issues) && detail.issues.length
              ? `\n${detail.issues.map((item: any) => item.repair_instruction || item.evidence || String(item)).join('\n')}`
              : ''}`
          : e?.message || '未知错误'
      alert('生成大纲失败：' + message)
    } finally {
      setGenerating(false)
      setGeneratingProgress(null)
    }
  }

  const handleClearOutline = async () => {
    if (!novelId || !currentNovel || generating) return
    const confirmed = window.confirm(
      '确定清空当前大纲并重新规划吗？\n\n'
      + '将清除：章节大纲、固定路线图、状态账本、不可逆事实、连续性审核和旧图谱。\n'
      + '不会删除已经同步的章节和正文内容。\n\n'
      + '清空后再次点击“AI 生成大纲”，将从第 1 章重新生成。',
    )
    if (!confirmed) return

    try {
      await novelApi.update(Number(novelId), {
        outline: '',
        story_roadmap: '',
        state_ledger: '',
        canon_facts: '[]',
        continuity_audits: '[]',
        knowledge_graph: '',
      })
      setOutline([])
      setGraph(null)
      setGeneratingProgress(null)
      setSelectedChapters(new Set())
      await fetchNovel(Number(novelId))
      alert('大纲规划数据已清空。再次点击“AI 生成大纲”将从第 1 章重新生成。')
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      alert('清空大纲失败：' + (typeof detail === 'string' ? detail : e?.message || '未知错误'))
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
    setSyncingAll(true)
    setSyncProgress({ done: 0, total: outline.length })
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
      for (let index = 0; index < outline.length; index++) {
        const item = outline[index]
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
        setSyncProgress({ done: index + 1, total: outline.length })
      }

      await fetchChapters(Number(novelId))
      alert('同步成功！')
    } catch (e) {
      alert('同步失败: ' + String(e))
    } finally {
      setSyncingAll(false)
      setSyncProgress(null)
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
      const res = await novelAiApi.getArchive(Number(novelId))
      if (res.data) setGraph(res.data)
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
      setGraph(null)

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
          await novelAiApi.updateGraphFromChapter(Number(novelId), ch.id)
          setRebuildProgress({ done: i + 1, total: chapters.length })
        } catch (e) {
          console.error(`Failed to update graph for chapter ${ch.chapter_number}:`, e)
        }
      }

      const archiveRes = await novelAiApi.getArchive(Number(novelId))
      if (archiveRes.data) setGraph(archiveRes.data)
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
        <Link to="/novels" style={{ color: 'var(--text-2)', textDecoration: 'none', fontSize: 14 }}>← 返回小说列表</Link>
      </div>

      <div style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h1 className="page-title">{currentNovel.title}</h1>
            {currentNovel.genre && <div style={{ color: 'var(--text-2)', marginBottom: 8 }}>{currentNovel.genre}</div>}
            <div style={{ color: 'var(--text-2)', lineHeight: 1.6 }}>{currentNovel.synopsis}</div>
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
              max={200}
              value={totalChapters}
              onChange={e => setTotalChapters(Math.min(200, Math.max(1, Number(e.target.value) || 1)))}
            />
          </div>
          <button className="btn btn-primary" onClick={handleGenerateOutline} disabled={generating}>
            {generating
              ? generatingProgress
                ? `生成、审核与返修中 ${generatingProgress.done}/${generatingProgress.total}...`
                : '生成、审核与返修中...'
              : outline.length > 0
                ? '继续生成未完成大纲'
                : 'AI 生成大纲'}
          </button>
          {outline.length > 0 && (
            <button
              className="btn"
              onClick={handleClearOutline}
              disabled={generating}
              style={{ color: 'var(--danger)', borderColor: 'rgba(255,69,58,.55)' }}
            >
              清空大纲
            </button>
          )}
          {outline.length > 0 && (
            <button className="btn" onClick={handleSyncToChapters} disabled={syncingAll}>
              {syncingAll && syncProgress
                ? `同步中 ${syncProgress.done}/${syncProgress.total}...`
                : `同步全部章节 (${outline.length} 章)`}
            </button>
          )}
        </div>
        {outline.length > 0 && (
          <div style={{ maxHeight: 400, overflow: 'auto', border: '.5px solid var(--border)', borderRadius: 12, padding: 12, background: 'rgba(255,255,255,.90)' }}>
            {outline.map((item, i) => (
              <div key={item.chapter_number} style={{ marginBottom: 12, paddingBottom: 12, borderBottom: '.5px solid var(--border-soft)' }}>
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
                      <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>{item.synopsis}</div>
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

      {/* Canon archive / knowledge graph */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontWeight: 700 }}>正史档案与图谱</div>
            <div style={{ color: 'var(--text-2)', fontSize: 12, marginTop: 2 }}>
              人物、资产、交易、物品、时间线和不可逆事实都会成为后续章节的生成约束
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-sm" onClick={handleLoadGraph} disabled={graphLoading}>
              {graphLoading ? '加载中...' : showGraph ? '刷新档案' : '查看正史档案'}
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
          <CanonArchivePanel
            novelId={Number(novelId)}
            archive={graph}
            onChange={setGraph}
          />
        )}
      </div>

      {/* Chapters List */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ fontWeight: 600 }}>章节列表 ({chapters.length})</div>
            {chapters.length > 0 && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--text-2)', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={selectedChapters.size === chapters.length && chapters.length > 0}
                  onChange={e => setSelectedChapters(e.target.checked ? new Set(chapters.map(c => c.id)) : new Set())}
                />
                全选
              </label>
            )}
            {selectedChapters.size > 0 && (
              <button className="btn btn-sm" style={{ color: 'var(--danger)', borderColor: 'rgba(255,69,58,.55)' }} onClick={handleBatchDelete} disabled={deleting}>
                {deleting ? '删除中...' : `删除选中 (${selectedChapters.size})`}
              </button>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-sm btn-primary" onClick={handleGenerateNext} disabled={generating || chapters.length === 0}>
              {generating ? '生成中...' : '继续生成下一章'}
            </button>
          </div>
        </div>

        {chapters.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-3)' }}>
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
                  <div className="card" style={{ padding: 14, background: 'rgba(255,255,255,.90)', color: 'var(--text)', borderColor: 'var(--border-soft)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>第 {chapter.chapter_number} 章：{chapter.title}</div>
                        {chapter.synopsis && <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>{chapter.synopsis}</div>}
                      </div>
                    </div>
                  </div>
                </Link>
                <button
                  className="btn btn-sm"
                  style={{ color: 'var(--danger)', borderColor: 'rgba(255,69,58,.55)', flexShrink: 0 }}
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
