import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { transport } from '../services/api'
import { novelAiApi } from '../services/api/novelAiApi'
import type { Chapter, ChapterContent } from '../types/models'

export default function ChapterEditor() {
  const { novelId, chapterId } = useParams<{ novelId: string; chapterId: string }>()
  const [chapter, setChapter] = useState<Chapter | null>(null)
  const [content, setContent] = useState('')
  const [wordCount, setWordCount] = useState(0)
  const [status, setStatus] = useState('draft')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    if (chapterId) {
      fetchChapter()
      fetchContent()
    }
  }, [chapterId])

  useEffect(() => {
    setWordCount(content.length)
  }, [content])

  const fetchChapter = async () => {
    try {
      const res = await transport.get<any>(`/novels/${novelId}/chapters`)
      const chapters = res.data || []
      const found = chapters.find((c: Chapter) => c.id === Number(chapterId))
      if (found) setChapter(found)
    } catch (e) {
      console.error('Failed to fetch chapter', e)
    }
  }

  const fetchContent = async () => {
    setLoading(true)
    try {
      // Fetch latest chapter content
      const res = await transport.get<any>(`/novels/${novelId}/chapters/${chapterId}/content`)
      if (res.data) {
        setContent(res.data.content || '')
        setWordCount(res.data.word_count || 0)
        setStatus(res.data.status || 'draft')
      }
    } catch (e) {
      console.error('Failed to fetch content', e)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    if (!chapterId) return
    setSaving(true)
    try {
      await transport.patch(`/novels/${novelId}/chapters/${chapterId}/content`, {
        content,
        status,
      })
      alert('保存成功！')
    } catch (e) {
      alert('保存失败: ' + String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleGenerate = async () => {
    if (!chapterId) return
    setGenerating(true)
    try {
      const res = await novelAiApi.generateChapter(Number(chapterId), {})
      if (res.data) {
        setContent(res.data.content)
        setWordCount(res.data.word_count)
        setStatus('generated')
        alert('生成成功！')
      }
    } catch (e) {
      alert('生成失败: ' + String(e))
    } finally {
      setGenerating(false)
    }
  }

  if (loading || !chapter) return <div>加载中...</div>

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 24 }}>
        <Link to={`/novels/${novelId}`} style={{ color: '#666', textDecoration: 'none', fontSize: 14 }}>
          ← 返回小说详情
        </Link>
      </div>

      <div style={{ marginBottom: 24 }}>
        <h1 className="page-title">第 {chapter.chapter_number} 章：{chapter.title}</h1>
        {chapter.synopsis && <div style={{ color: '#888', marginTop: 8 }}>{chapter.synopsis}</div>}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
            <div style={{ fontSize: 13, color: '#666' }}>字数: {wordCount}</div>
            <div style={{ fontSize: 13, color: '#666' }}>
              状态: {status === 'draft' ? '草稿' : status === 'generated' ? '已生成' : '已审阅'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-primary" onClick={handleGenerate} disabled={generating}>
              {generating ? '生成中...' : 'AI 生成内容'}
            </button>
            <button className="btn" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>

        <textarea
          className="textarea"
          value={content}
          onChange={e => setContent(e.target.value)}
          rows={25}
          placeholder="章节内容将在此显示，或点击「AI 生成内容」自动生成约 3000 字的章节内容..."
          style={{ fontFamily: 'monospace', fontSize: 14, lineHeight: 1.8 }}
        />
      </div>

      <div style={{ fontSize: 12, color: '#999', textAlign: 'center' }}>
        提示：AI 生成的内容会自动与上一章衔接，确保情节连贯
      </div>
    </div>
  )
}
