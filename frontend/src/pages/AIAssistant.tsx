import { useEffect, useMemo, useRef, useState } from 'react'

import {
  manuscriptApi,
  type InspectionType,
  type ManuscriptDocument,
  type ManuscriptReport,
  type ManuscriptReportSummary,
} from '../services/api/manuscriptApi'
import { novelApi } from '../services/api/novelApi'
import type { Novel } from '../types/models'
import { exportTxt } from '../utils/export'


const TYPE_META: Record<InspectionType, { title: string; subtitle: string; scoreLabel: string }> = {
  quality: {
    title: '小说质量体检',
    subtitle: '逐章检查结构、人物、逻辑、节奏、情绪、对话、语言与追读力',
    scoreLabel: '综合质量分',
  },
  ai_trace: {
    title: 'AI味体检',
    subtitle: '逐章定位模板句、机械节奏、过度解释、角色同声与重复表达',
    scoreLabel: 'AI痕迹风险',
  },
}

function array(value: unknown): any[] {
  return Array.isArray(value) ? value : []
}

function printable(value: unknown): string {
  if (typeof value === 'string') return value
  if (value == null) return ''
  return JSON.stringify(value, null, 2)
}

function reportAsText(item: ManuscriptReport): string {
  const report = item.report || {}
  const lines = [
    `${TYPE_META[item.inspection_type].title}报告`,
    `作品：${item.source_name}`,
    `字数：${item.word_count}`,
    `${TYPE_META[item.inspection_type].scoreLabel}：${report.overall_score ?? 0}/100`,
    `结论：${report.verdict || ''}`,
    '',
    `总体评价：${report.summary || ''}`,
    '',
    '【分项评分】',
  ]
  for (const dimension of array(report.dimensions)) {
    lines.push(`- ${dimension.name || '未命名维度'}：${dimension.score ?? '-'}分`)
    for (const finding of array(dimension.findings)) lines.push(`  问题：${printable(finding)}`)
    for (const suggestion of array(dimension.suggestions)) lines.push(`  建议：${printable(suggestion)}`)
  }
  const issues = array(report.critical_issues).length ? array(report.critical_issues) : array(report.evidence)
  lines.push('', '【重点问题】')
  for (const issue of issues) {
    lines.push(`- [${issue.severity || '提示'}] ${issue.location || ''} ${issue.issue || issue.pattern || ''}`)
    if (issue.evidence || issue.excerpt) lines.push(`  证据：${issue.evidence || issue.excerpt}`)
    if (issue.suggestion) lines.push(`  建议：${issue.suggestion}`)
  }
  lines.push('', '【逐章报告】')
  for (const chapter of array(report.chapter_reviews)) {
    lines.push(`- ${chapter.document_name || `第${chapter.chapter_number || '-'}章`}：${chapter.score ?? '-'}分 ${chapter.summary || ''}`)
    for (const issue of array(chapter.issues)) lines.push(`  · ${issue.issue || ''}；证据：${issue.evidence || ''}；建议：${issue.suggestion || ''}`)
  }
  lines.push('', '【优先修改清单】')
  for (const action of array(report.prioritized_actions)) lines.push(`- ${printable(action)}`)
  if (report.disclaimer) lines.push('', `说明：${report.disclaimer}`)
  return lines.join('\n')
}

export default function AIAssistant() {
  const [inspectionType, setInspectionType] = useState<InspectionType>('quality')
  const [novels, setNovels] = useState<Novel[]>([])
  const [sourceMode, setSourceMode] = useState<'novel' | 'file' | 'folder'>('novel')
  const [novelId, setNovelId] = useState('')
  const [sourceName, setSourceName] = useState('')
  const [fileText, setFileText] = useState('')
  const [documents, setDocuments] = useState<ManuscriptDocument[]>([])
  const folderInputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reports, setReports] = useState<ManuscriptReportSummary[]>([])
  const [activeReport, setActiveReport] = useState<ManuscriptReport | null>(null)

  const loadReports = () => manuscriptApi.listReports().then(result => setReports(result.data || []))

  useEffect(() => {
    novelApi.list().then(result => {
      setNovels(result.data || [])
      if (result.data?.length) setNovelId(String(result.data[0].id))
    })
    loadReports().catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!busy) return
    const timer = window.setInterval(() => loadReports().catch(() => undefined), 3000)
    return () => window.clearInterval(timer)
  }, [busy])

  const meta = TYPE_META[inspectionType]
  const canInspect = sourceMode === 'novel'
    ? Boolean(novelId)
    : sourceMode === 'folder'
      ? documents.length > 0
      : fileText.trim().length >= 200
  const issues = useMemo(() => {
    const report = activeReport?.report || {}
    return array(report.critical_issues).length ? array(report.critical_issues) : array(report.evidence)
  }, [activeReport])

  const handleFile = async (file?: File) => {
    if (!file) return
    if (file.size > 4 * 1024 * 1024) {
      setError('单文件不能超过 4MB；长篇小说请使用“导入章节文件夹”。')
      return
    }
    setSourceName(file.name.replace(/\.(txt|md)$/i, ''))
    setFileText(await file.text())
    setDocuments([])
    setError('')
  }

  const handleFolder = async (fileList?: FileList | null) => {
    const files = Array.from(fileList || [])
      .filter(file => /\.(txt|md)$/i.test(file.name))
      .sort((left, right) => (left.webkitRelativePath || left.name).localeCompare(
        right.webkitRelativePath || right.name,
        'zh-CN',
        { numeric: true, sensitivity: 'base' },
      ))
    if (!files.length) {
      setDocuments([])
      setError('所选文件夹中没有 TXT 或 Markdown 章节文件。')
      return
    }
    const next = (await Promise.all(files.map(async (file, index) => {
      const relative = file.webkitRelativePath || file.name
      const match = file.name.match(/第?\s*(\d+)\s*[章回节]?/)
      return {
        name: relative,
        content: await file.text(),
        chapter_number: match ? Number(match[1]) : index + 1,
      }
    }))).filter(item => item.content.trim().length >= 20)
    const total = next.reduce((sum, item) => sum + item.content.length, 0)
    if (total > 20_000_000) {
      setDocuments([])
      setError('文件夹正文超过 2000 万字符，请拆分作品后体检。')
      return
    }
    setSourceName(files[0].webkitRelativePath?.split('/')[0] || '导入小说文件夹')
    setDocuments(next)
    setFileText('')
    setError('')
  }

  const inspect = async () => {
    if (!canInspect || busy) return
    setBusy(true)
    setError('')
    try {
      const response = await manuscriptApi.inspect({
        inspection_type: inspectionType,
        ...(sourceMode === 'novel'
          ? { novel_id: Number(novelId) }
          : sourceMode === 'folder'
            ? { source_name: sourceName || '导入小说文件夹', source_documents: documents }
            : { source_name: sourceName || '导入小说', source_text: fileText }),
      })
      if (response.data) setActiveReport(response.data)
    } catch (caught: any) {
      setError(caught?.response?.data?.detail || caught?.message || '体检失败；已完成章节会保留，可再次点击继续。')
    } finally {
      await loadReports().catch(() => undefined)
      setBusy(false)
    }
  }

  const openReport = async (reportId: number) => {
    const response = await manuscriptApi.getReport(reportId)
    if (response.data) {
      setInspectionType(response.data.inspection_type)
      setActiveReport(response.data)
    }
  }

  const progressReport = reports.find(report => report.status !== 'completed')

  return (
    <div style={{ maxWidth: 1100 }}>
      <div style={{ marginBottom: 22 }}>
        <div className="page-title">AI 助手</div>
        <div className="page-subtitle">对书架作品或本地章节文件夹执行逐章完整体检，并生成全书报告</div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
          {(Object.keys(TYPE_META) as InspectionType[]).map(type => (
            <button key={type} onClick={() => { setInspectionType(type); setActiveReport(null) }} style={{
              border: 0,
              borderBottom: inspectionType === type ? '3px solid var(--primary)' : '3px solid transparent',
              background: inspectionType === type ? 'rgba(25,117,91,.08)' : 'transparent',
              padding: '18px 22px', textAlign: 'left', cursor: 'pointer', color: 'var(--text-1)',
            }}>
              <div style={{ fontWeight: 750, fontSize: 17 }}>{TYPE_META[type].title}</div>
              <div style={{ color: 'var(--text-2)', fontSize: 12, marginTop: 5 }}>{TYPE_META[type].subtitle}</div>
            </button>
          ))}
        </div>

        <div style={{ padding: 22 }}>
          <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
            <button className={`btn ${sourceMode === 'novel' ? 'btn-primary' : ''}`} onClick={() => setSourceMode('novel')}>选择书架小说</button>
            <button className={`btn ${sourceMode === 'folder' ? 'btn-primary' : ''}`} onClick={() => { setSourceMode('folder'); setTimeout(() => folderInputRef.current?.click(), 0) }}>导入章节文件夹</button>
            <button className={`btn ${sourceMode === 'file' ? 'btn-primary' : ''}`} onClick={() => setSourceMode('file')}>导入单个 TXT</button>
          </div>

          {sourceMode === 'novel' && (
            <select className="input" value={novelId} onChange={event => setNovelId(event.target.value)}>
              {!novels.length && <option value="">书架中暂无小说</option>}
              {novels.map(novel => <option key={novel.id} value={novel.id}>{novel.title}</option>)}
            </select>
          )}
          {sourceMode === 'file' && (
            <label style={{ display: 'block', border: '1px dashed var(--border)', borderRadius: 12, padding: 20, cursor: 'pointer', textAlign: 'center', background: 'rgba(255,255,255,.45)' }}>
              <input type="file" accept=".txt,.md,text/plain,text/markdown" style={{ display: 'none' }} onChange={event => handleFile(event.target.files?.[0])} />
              <strong>{sourceName || '点击选择 TXT / Markdown 小说文件'}</strong>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 6 }}>{fileText ? `已读取 ${fileText.length.toLocaleString()} 字符` : '短篇作品单文件最大 4MB'}</div>
            </label>
          )}
          {sourceMode === 'folder' && (
            <div style={{ border: '1px dashed var(--border)', borderRadius: 12, padding: 20, textAlign: 'center', background: 'rgba(255,255,255,.45)' }}>
              <input ref={folderInputRef} type="file" multiple accept=".txt,.md,text/plain,text/markdown" style={{ display: 'none' }} {...({ webkitdirectory: '', directory: '' } as any)} onChange={event => handleFolder(event.target.files)} />
              <strong>{documents.length ? sourceName : '选择包含分章 TXT / Markdown 的小说文件夹'}</strong>
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 6 }}>
                {documents.length
                  ? `已读取 ${documents.length} 个章节文件，共 ${documents.reduce((sum, item) => sum + item.content.length, 0).toLocaleString()} 字符`
                  : '按章节号排序，逐章完整送检；中断后可从检查点继续'}
              </div>
              <button className="btn btn-sm" style={{ marginTop: 10 }} onClick={() => folderInputRef.current?.click()}>重新选择文件夹</button>
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 16 }}>
            <button className="btn btn-primary" disabled={!canInspect || busy} onClick={inspect}>
              {busy ? '逐章体检中…' : `开始${meta.title}`}
            </button>
            <span style={{ fontSize: 12, color: 'var(--text-3)' }}>沿用“设置”中的当前 AI 模式；失败后再次点击会从已保存批次继续</span>
          </div>
          {progressReport && progressReport.total_chapters > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-2)' }}>
                <span>{progressReport.verdict}</span><span>{progressReport.completed_chapters}/{progressReport.total_chapters} 章</span>
              </div>
              <div style={{ height: 7, background: 'rgba(25,117,91,.12)', borderRadius: 8, marginTop: 7, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${Math.round(progressReport.completed_chapters / progressReport.total_chapters * 100)}%`, background: 'var(--primary)' }} />
              </div>
            </div>
          )}
          {error && <div style={{ marginTop: 12, color: 'var(--danger)', whiteSpace: 'pre-wrap' }}>{printable(error)}</div>}
        </div>
      </div>

      {activeReport && activeReport.report.status === 'completed' && (
        <div className="card" style={{ marginTop: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 20 }}>
            <div><div style={{ color: 'var(--text-3)', fontSize: 12 }}>{TYPE_META[activeReport.inspection_type].title} · {activeReport.source_name}</div><h2>{activeReport.report.verdict}</h2><div style={{ color: 'var(--text-2)', lineHeight: 1.7 }}>{activeReport.report.summary}</div></div>
            <div style={{ minWidth: 120, textAlign: 'center', border: '1px solid var(--border)', borderRadius: 16, padding: 14 }}><div style={{ fontSize: 34, color: 'var(--primary)', fontWeight: 800 }}>{activeReport.report.overall_score ?? 0}</div><div style={{ fontSize: 12 }}>{TYPE_META[activeReport.inspection_type].scoreLabel}</div></div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(210px,1fr))', gap: 10, marginTop: 20 }}>
            {array(activeReport.report.dimensions).map((dimension, index) => <div key={index} style={{ padding: 14, border: '1px solid var(--border)', borderRadius: 12 }}><div style={{ display: 'flex', justifyContent: 'space-between' }}><strong>{dimension.name}</strong><b>{dimension.score}</b></div>{array(dimension.findings).slice(0, 2).map((finding, itemIndex) => <div key={itemIndex} style={{ fontSize: 12, marginTop: 7 }}>· {printable(finding)}</div>)}</div>)}
          </div>
          <h3 style={{ marginTop: 22 }}>重点问题与原文证据</h3>
          {issues.map((issue, index) => <div key={index} style={{ borderLeft: '4px solid var(--danger)', padding: '10px 14px', marginTop: 8, background: 'rgba(255,255,255,.45)' }}><strong>{issue.location ? `${issue.location} · ` : ''}{issue.issue || issue.pattern}</strong>{(issue.evidence || issue.excerpt) && <div style={{ marginTop: 5 }}>证据：“{issue.evidence || issue.excerpt}”</div>}{issue.suggestion && <div style={{ color: 'var(--primary)', marginTop: 5 }}>建议：{issue.suggestion}</div>}</div>)}
          <div style={{ marginTop: 18, display: 'flex', gap: 8 }}><button className="btn btn-primary" onClick={() => exportTxt(reportAsText(activeReport), `${activeReport.source_name}-${TYPE_META[activeReport.inspection_type].title}报告.txt`)}>导出完整报告</button><button className="btn" onClick={() => setActiveReport(null)}>关闭报告</button></div>
          <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 12 }}>{activeReport.report.methodology}</div>
        </div>
      )}

      <div className="card" style={{ marginTop: 20 }}>
        <div style={{ fontWeight: 700, marginBottom: 12 }}>历史体检报告与检查点</div>
        {!reports.length ? <div style={{ color: 'var(--text-3)' }}>暂无报告</div> : reports.map(report => (
          <div key={report.id} style={{ display: 'flex', alignItems: 'center', gap: 12, borderBottom: '1px solid var(--border)', padding: '10px 0' }}>
            <div style={{ flex: 1 }}><strong>{report.source_name}</strong><div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 3 }}>{TYPE_META[report.inspection_type].title} · {new Date(report.created_at).toLocaleString()} · {report.word_count.toLocaleString()} 字{report.total_chapters > 0 && ` · ${report.completed_chapters}/${report.total_chapters} 章`}</div></div>
            <b style={{ color: report.status === 'failed' ? 'var(--danger)' : 'var(--primary)' }}>{report.status === 'completed' ? report.overall_score : report.status === 'failed' ? '可续检' : '检查中'}</b>
            <button className="btn btn-sm" onClick={() => openReport(report.id)}>查看</button>
            <button className="btn btn-sm" onClick={async () => { if (!confirm('确定删除这份体检报告和检查点吗？')) return; await manuscriptApi.deleteReport(report.id); await loadReports() }}>删除</button>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-3)', lineHeight: 1.7, marginTop: 14 }}>全部章节会按顺序完整送检，不使用抽样代替全文。AI味体检是文体风险分析，不是作者身份鉴定。</div>
    </div>
  )
}
