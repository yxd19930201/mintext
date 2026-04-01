import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useNovelStore } from '../stores/novelStore'
import { novelAiApi } from '../services/api/novelAiApi'
import { novelApi } from '../services/api/novelApi'
import type { ChapterOutlineItem } from '../types/models'

export default function NovelDetail() {
  const { novelId } = useParams<{ novelId: string }>()
  const { currentNovel, chapters, loading, fetchNovel, fetchChapters, createChapter } = useNovelStore()
  const [outline, setOutline] = useState<ChapterOutlineItem[]>([])
  const [generating, setGenerating] = useState(false)
  const [totalChapters, setTotalChapters] = useState(50)
  const [showAiPanel, setShowAiPanel] = useState(false)
  const [batchGenerating, setBatchGenerating] = useState(false)

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
      for (const item of outline) {
        await createChapter(Number(novelId), {
          title: item.title,
          chapter_number: item.chapter_number,
          synopsis: item.synopsis,
        })
      }
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
        <h1 className="page-title">{currentNovel.title}</h1>
        {currentNovel.genre && <div style={{ color: '#666', marginBottom: 8 }}>{currentNovel.genre}</div>}
        <div style={{ color: '#888', lineHeight: 1.6 }}>{currentNovel.synopsis}</div>
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
          <div style={{ fontWeight: 600 }}>章节列表 ({chapters.length})</div>
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
              <Link
                key={chapter.id}
                to={`/novels/${novelId}/chapters/${chapter.id}`}
                style={{ textDecoration: 'none', color: 'inherit' }}
              >
                <div className="card" style={{ padding: 12, background: '#fafafa' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>第 {chapter.chapter_number} 章：{chapter.title}</div>
                      {chapter.synopsis && <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>{chapter.synopsis}</div>}
                    </div>
                    <div style={{ fontSize: 12, color: '#999' }}>
                      {/* Word count will be shown after content is generated */}
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
