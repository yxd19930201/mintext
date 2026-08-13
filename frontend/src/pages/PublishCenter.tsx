import { useEffect, useState } from 'react'
import { browserExtensionApi, type BrowserExtensionStatus, type BrowserJob } from '../services/api/browserExtensionApi'
import { novelApi } from '../services/api/novelApi'
import { chapterApi } from '../services/api/chapterApi'
import type { Chapter, Novel } from '../types/models'

const STATUS: Record<string, string> = {
  queued: '等待浏览器助手', leased: '已领取', running: '执行中', completed: '已完成',
  failed: '失败', waiting_user: '等待人工处理', adapter_outdated: '网页适配器需更新',
}

export default function PublishCenter() {
  const [novels, setNovels] = useState<Novel[]>([])
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [jobs, setJobs] = useState<BrowserJob[]>([])
  const [novelId, setNovelId] = useState('')
  const [chapterId, setChapterId] = useState('')
  const [platformBookId, setPlatformBookId] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [extensionStatus, setExtensionStatus] = useState<BrowserExtensionStatus>({ connected: false })

  const refreshJobs = async () => {
    const [jobsResponse, statusResponse] = await Promise.all([
      browserExtensionApi.listJobs(), browserExtensionApi.status(),
    ])
    setJobs(jobsResponse.data || [])
    setExtensionStatus(statusResponse.data || { connected: false })
  }

  useEffect(() => {
    novelApi.list().then(response => setNovels(response.data || [])).catch(error => setMessage(error.message))
    refreshJobs().catch(error => setMessage(error.message))
    const timer = window.setInterval(() => refreshJobs().catch(() => {}), 3000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!novelId) { setChapters([]); setChapterId(''); return }
    chapterApi.list(Number(novelId)).then(response => setChapters(response.data || [])).catch(error => setMessage(error.message))
  }, [novelId])

  const queue = async (operation: string, payload: Record<string, unknown> = {}) => {
    setBusy(true); setMessage('')
    try {
      await browserExtensionApi.createJob(operation, payload)
      setMessage('任务已加入队列，请保持青玉浏览器助手和番茄作者后台开启。')
      await refreshJobs()
    } catch (error: any) { setMessage(error.message) } finally { setBusy(false) }
  }

  const publish = async () => {
    if (!chapterId || !platformBookId.trim()) { setMessage('请选择章节并填写番茄作品 ID。'); return }
    setBusy(true); setMessage('')
    try {
      await browserExtensionApi.publishChapter({ chapter_id: Number(chapterId), platform_book_id: platformBookId.trim() })
      setMessage('章节发布任务已加入队列。实际发布前请确认番茄账号和作品 ID 正确。')
      await refreshJobs()
    } catch (error: any) { setMessage(error.message) } finally { setBusy(false) }
  }

  const openExtensionFolder = async () => {
    try {
      if (!window.minitextDesktop?.browserExtension) {
        setMessage('请在安装目录的 resources/browser-extension 中加载扩展。')
        return
      }
      const path = await window.minitextDesktop.browserExtension.openFolder()
      setMessage(`已打开扩展目录：${path}`)
    } catch (error: any) { setMessage(error.message) }
  }

  return (
    <div className="page-container" style={{ maxWidth: 1100 }}>
      <div className="page-header">
        <div><h1>发布中心</h1><p>通过青玉浏览器助手，将本地正文安全同步到已登录的番茄作者后台。发布操作均需在这里明确创建。</p></div>
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <h3>1. 安装并连接浏览器助手</h3>
        <p style={{ color: 'var(--text-2)' }}>在 Chrome/Edge 扩展管理页开启开发者模式，加载打开的目录。启动桌面端后，在扩展弹窗点击“连接本机青玉书房”。</p>
        <p style={{ color: extensionStatus.connected ? 'var(--primary)' : '#b42318' }}>
          当前状态：{extensionStatus.connected ? `浏览器助手已连接（${extensionStatus.browser || '浏览器'} ${extensionStatus.extension_version || ''}）` : '浏览器助手未连接'}
        </p>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="btn btn-primary" disabled={busy} onClick={openExtensionFolder}>打开扩展目录</button>
          <button className="btn" disabled={busy} onClick={() => queue('CHECK_SESSION')}>检测番茄登录</button>
          <button className="btn" disabled={busy} onClick={() => queue('LIST_BOOKS')}>读取番茄作品</button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <h3>2. 发布单章</h3>
        <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          <label>本地小说<select value={novelId} onChange={event => setNovelId(event.target.value)}><option value="">请选择</option>{novels.map(novel => <option key={novel.id} value={novel.id}>{novel.title}</option>)}</select></label>
          <label>本地章节<select value={chapterId} onChange={event => setChapterId(event.target.value)}><option value="">请选择</option>{chapters.map(chapter => <option key={chapter.id} value={chapter.id}>第 {chapter.chapter_number} 章 · {chapter.title}</option>)}</select></label>
          <label>番茄作品 ID<input value={platformBookId} onChange={event => setPlatformBookId(event.target.value)} placeholder="番茄后台作品 ID" /></label>
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={publish} style={{ marginTop: 14 }}>确认并创建发布任务</button>
        {message && <p style={{ marginTop: 12, color: message.includes('已') ? 'var(--primary)' : '#b42318' }}>{message}</p>}
      </div>

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><h3>任务记录</h3><button className="btn btn-sm" onClick={refreshJobs}>刷新</button></div>
        {jobs.length === 0 ? <p style={{ color: 'var(--text-2)' }}>暂无浏览器任务。</p> : jobs.map(job => (
          <div key={job.id} style={{ padding: '12px 0', borderTop: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><strong>{job.operation}</strong><span>{STATUS[job.status] || job.status}</span></div>
            <small style={{ color: 'var(--text-2)' }}>{job.id}{job.error ? ` · ${job.error}` : ''}</small>
          </div>
        ))}
      </div>
    </div>
  )
}
