import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { transport } from '../services/api'
import { novelAiApi } from '../services/api/novelAiApi'
import { exportTxt } from '../utils/export'
import type { Chapter } from '../types/models'
import { usePersistentState } from '../stores/persistentTaskStore'

interface ReviewMatch {
  start: number
  end: number
  text: string
}

interface ReviewIssue {
  type?: string
  evidence?: string
  conflict_with?: string
  repair_instruction?: string
  matches?: ReviewMatch[]
}

interface ChapterReviewDraft {
  message: string
  candidateContent: string
  issues: ReviewIssue[]
}

function chapterReviewDraft(error: any): ChapterReviewDraft | null {
  const detail = error?.response?.data?.detail
  if (
    detail?.code !== 'CHAPTER_REVIEW_REQUIRED'
    || typeof detail?.candidate_content !== 'string'
  ) return null
  return {
    message: typeof detail.message === 'string' ? detail.message : '正文校验未通过',
    candidateContent: detail.candidate_content,
    issues: Array.isArray(detail.issues) ? detail.issues : [],
  }
}

function highlightedReviewContent(draft: ChapterReviewDraft) {
  const ranges: Array<{ start: number; end: number; issueIndexes: number[] }> = []
  draft.issues.forEach((issue, issueIndex) => {
    for (const match of issue.matches || []) {
      const text = String(match.text || '')
      let start = Number(match.start)
      let end = Number(match.end)
      if (!Number.isFinite(start) || !Number.isFinite(end) || draft.candidateContent.slice(start, end) !== text) {
        start = draft.candidateContent.indexOf(text)
        end = start + text.length
      }
      if (text && start >= 0 && end > start) ranges.push({ start, end, issueIndexes: [issueIndex] })
    }
  })
  ranges.sort((a, b) => a.start - b.start || a.end - b.end)
  const merged: typeof ranges = []
  for (const range of ranges) {
    const previous = merged[merged.length - 1]
    if (previous && range.start <= previous.end) {
      previous.end = Math.max(previous.end, range.end)
      previous.issueIndexes = Array.from(new Set([...previous.issueIndexes, ...range.issueIndexes]))
    } else {
      merged.push({ ...range })
    }
  }
  if (!merged.length) return draft.candidateContent

  const nodes = []
  let cursor = 0
  merged.forEach((range, index) => {
    if (range.start > cursor) nodes.push(draft.candidateContent.slice(cursor, range.start))
    const suggestions = range.issueIndexes
      .map(issueIndex => draft.issues[issueIndex]?.repair_instruction)
      .filter(Boolean)
      .join('；')
    nodes.push(
      <mark className="review-highlight" title={suggestions || '此处需要修改'} key={`review-${index}`}>
        {draft.candidateContent.slice(range.start, range.end)}
      </mark>,
    )
    cursor = range.end
  })
  if (cursor < draft.candidateContent.length) nodes.push(draft.candidateContent.slice(cursor))
  return nodes
}

function errorMessage(error: any): string {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const message = typeof detail.message === 'string' ? detail.message : ''
    const issues = Array.isArray(detail.issues)
      ? detail.issues
          .map((item: any) => item?.repair_instruction || item?.evidence || item?.type)
          .filter(Boolean)
          .join('\n')
      : ''
    return [message, issues].filter(Boolean).join('\n') || JSON.stringify(detail)
  }
  return error?.message || String(error)
}

export default function ChapterEditor() {
  const { novelId, chapterId } = useParams<{ novelId: string; chapterId: string }>()
  const [chapter, setChapter] = useState<Chapter | null>(null)
  const [content, setContent] = usePersistentState(`chapter:${chapterId}:content`, '')
  const [wordCount, setWordCount] = usePersistentState(`chapter:${chapterId}:wordCount`, 0)
  const [status, setStatus] = usePersistentState(`chapter:${chapterId}:status`, 'draft')
  const [loading, setLoading] = useState(true)
  const [noContent, setNoContent] = usePersistentState(`chapter:${chapterId}:noContent`, false)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = usePersistentState(`chapter:${chapterId}:generating`, false)
  const [reviewDraft, setReviewDraft] = usePersistentState<ChapterReviewDraft | null>(`chapter:${chapterId}:reviewDraft`, null)
  const [manualReview, setManualReview] = usePersistentState(`chapter:${chapterId}:manualReview`, false)
  const [reviewChoiceOpen, setReviewChoiceOpen] = useState(false)

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
    setNoContent(false)
    try {
      const res = await transport.get<any>(`/novels/${novelId}/chapters/${chapterId}/content`)
      if (res.data) {
        setContent(res.data.content || '')
        setWordCount(res.data.word_count || 0)
        setStatus(res.data.status || 'draft')
      }
    } catch (e: any) {
      if (e?.response?.status === 404) {
        setNoContent(true)
      } else {
        console.error('Failed to fetch content', e)
      }
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    if (!chapterId) return
    setSaving(true)
    try {
      const savedStatus = status === 'manual_review' ? 'generated' : status
      await transport.patch(`/novels/${novelId}/chapters/${chapterId}/content`, {
        content,
        status: savedStatus,
      })
      setStatus(savedStatus)
      setReviewDraft(null)
      setManualReview(false)
      alert('保存成功！')
      // Update knowledge graph in background (non-blocking)
      novelAiApi.updateGraphFromChapter(Number(novelId), Number(chapterId)).catch(() => {})
    } catch (e) {
      alert('保存失败: ' + String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleGenerate = async (options?: { restartFailedGeneration?: boolean; skipConfirm?: boolean }) => {
    if (!chapterId) return
    // A rejected candidate copied into the editor is not a formal saved
    // ChapterContent version.  Treat it as a failed-generation restart even
    // though the textarea is non-empty; otherwise the backend correctly
    // rejects it as an attempt to regenerate a formal version that does not
    // exist yet.
    const restartFailedGeneration = Boolean(
      options?.restartFailedGeneration || manualReview || status === 'manual_review'
    )
    const regenerate = Boolean(content.trim()) && !restartFailedGeneration
    if (regenerate && !options?.skipConfirm && !window.confirm(
      '确定重新生成本章吗？\n\n系统会保留旧正文版本，并在生成时回滚本章写入的状态账本、交易记录和不可逆事实。新正文审核通过后才会替换当前版本。'
    )) return
    setGenerating(true)
    try {
      const res = await novelAiApi.generateChapter(Number(chapterId), {
        regenerate,
        restart_failed_generation: restartFailedGeneration,
      })
      if (res.data) {
        setContent(res.data.content)
        setWordCount(res.data.word_count)
        setStatus('generated')
        setNoContent(false)
        setReviewDraft(null)
        setManualReview(false)
        alert('生成成功！')
      }
    } catch (e: any) {
      const rejectedDraft = chapterReviewDraft(e)
      if (rejectedDraft) {
        setReviewDraft(rejectedDraft)
        setReviewChoiceOpen(true)
      } else {
        alert('生成失败: ' + errorMessage(e))
      }
    } finally {
      setGenerating(false)
    }
  }

  const handleManualReview = () => {
    if (!reviewDraft) return
    setContent(reviewDraft.candidateContent)
    setWordCount(reviewDraft.candidateContent.length)
    setStatus('manual_review')
    setNoContent(false)
    setManualReview(true)
    setReviewChoiceOpen(false)
  }

  const handleRegenerateRejected = () => {
    setReviewChoiceOpen(false)
    setManualReview(false)
    setReviewDraft(null)
    void handleGenerate({ restartFailedGeneration: true, skipConfirm: true })
  }

  if (loading || !chapter) return <div>加载中...</div>

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 24 }}>
        <Link to={`/novels/${novelId}`} style={{ color: 'var(--text-2)', textDecoration: 'none', fontSize: 14 }}>
          ← 返回小说详情
        </Link>
      </div>

      <div style={{ marginBottom: 24 }}>
        <h1 className="page-title">第 {chapter.chapter_number} 章：{chapter.title}</h1>
        {chapter.synopsis && <div style={{ color: 'var(--text-2)', marginTop: 8 }}>{chapter.synopsis}</div>}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
            <div style={{ fontSize: 13, color: 'var(--text-2)' }}>字数: {wordCount}</div>
            <div style={{ fontSize: 13, color: 'var(--text-2)' }}>
              状态: {status === 'draft' ? '草稿' : status === 'generated' ? '已生成' : status === 'manual_review' ? '人工修改中' : '已审阅'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={() => {
              const filename = chapter ? `第${chapter.chapter_number}章_${chapter.title}` : `章节${chapterId}`
              exportTxt(content, filename)
            }} disabled={!content}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              导出
            </button>
            <button className="btn btn-primary" onClick={() => handleGenerate()} disabled={generating}>
              {generating
                ? '生成、审核与返修中...'
                : manualReview
                  ? '重新生成候选正文'
                  : content.trim()
                    ? '重新生成'
                    : 'AI 生成内容'}
            </button>
            <button className="btn" onClick={handleSave} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </button>
          </div>
        </div>

        {noContent && (
          <div style={{ padding: '12px 16px', background: 'rgba(255,214,10,.1)', border: '.5px solid rgba(255,214,10,.22)', borderRadius: 12, marginBottom: 12, fontSize: 13, color: 'var(--warning)' }}>
            本章暂无内容，点击「AI 生成内容」自动生成，或直接在下方编辑。
          </div>
        )}
        {manualReview && reviewDraft && (
          <div className="review-workbench">
            <div className="review-workbench-title">校验未通过的候选正文</div>
            <div className="review-workbench-help">红色底纹是系统定位到的修改点。请结合下方修改意见，在正文编辑框中手动调整后保存。</div>
            <div className="review-candidate-content">{highlightedReviewContent(reviewDraft)}</div>
            <div className="review-opinions">
              <div className="review-opinions-title">修改意见</div>
              {reviewDraft.issues.map((issue, index) => (
                <div className="review-opinion" key={`${issue.type || 'issue'}-${index}`}>
                  <div className="review-opinion-index">{index + 1}</div>
                  <div>
                    <div>{issue.repair_instruction || '请根据证据修正正文中的连续性问题。'}</div>
                    {issue.evidence && <div className="review-opinion-evidence">问题证据：{issue.evidence}</div>}
                    {issue.conflict_with && <div className="review-opinion-evidence">冲突依据：{issue.conflict_with}</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        <textarea
          className="textarea"
          value={content}
          onChange={e => setContent(e.target.value)}
          rows={25}
          placeholder="章节内容将在此显示，或点击「AI 生成内容」自动生成约 3000 字的章节内容..."
          style={{ fontFamily: 'monospace', fontSize: 14, lineHeight: 1.8 }}
        />
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-3)', textAlign: 'center' }}>
        提示：正文通过路线图、状态账本和不可逆事实审核后才会保存；发现冲突会自动返修
      </div>

      {reviewChoiceOpen && reviewDraft && (
        <div className="review-choice-overlay" role="dialog" aria-modal="true" aria-labelledby="review-choice-title">
          <div className="review-choice-dialog">
            <div id="review-choice-title" className="review-choice-title">正文校验未通过</div>
            <div className="review-choice-message">{reviewDraft.message}</div>
            <div className="review-choice-summary">
              已保留本次生成的 {reviewDraft.candidateContent.length} 字候选正文，共发现 {reviewDraft.issues.length} 个修改点。
            </div>
            <div className="review-choice-actions">
              <button className="btn" onClick={handleManualReview}>生成后本地手动修改</button>
              <button className="btn btn-primary" onClick={handleRegenerateRejected}>重新生成</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
