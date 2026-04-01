import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { scriptApi } from '../services/api/scriptApi'
import { episodeApi } from '../services/api/episodeApi'
import { aiApi } from '../services/api/aiApi'
import type { Script, Episode } from '../types/models'

const STATUS_COLOR: Record<string, string> = {
  draft: '#8b90b8',
  generated: '#34d399',
  reviewed: '#7c6af7',
}

export default function ScriptEditor() {
  const { projectId, episodeId } = useParams<{ projectId: string; episodeId: string }>()
  const epId = Number(episodeId)
  const [episode, setEpisode] = useState<Episode | null>(null)
  const [script, setScript] = useState<Script | null>(null)
  const [content, setContent] = useState('')
  const [prompt, setPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [saved, setSaved] = useState(false)
  const [activeTab, setActiveTab] = useState<'editor' | 'prompt'>('editor')

  useEffect(() => {
    episodeApi.get(Number(projectId), epId).then(res => setEpisode(res.data!))
    scriptApi.list(epId).then((res) => {
      if (res.data.length > 0) {
        setScript(res.data[0])
        setContent(res.data[0].content ?? '')
        setPrompt(res.data[0].ai_prompt ?? '')
      }
    })
  }, [epId, projectId])

  const handleSave = async () => {
    if (script) {
      const res = await scriptApi.update(epId, script.id, { content, ai_prompt: prompt })
      setScript(res.data!)
    } else {
      const res = await scriptApi.create(epId, { content, ai_prompt: prompt })
      setScript(res.data!)
    }
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await aiApi.generateScript(epId, { extra_context: prompt || undefined })
      setContent(res.data?.content ?? '')
      const updated = await scriptApi.list(epId)
      if (updated.data.length > 0) setScript(updated.data[0])
    } finally {
      setGenerating(false)
    }
  }

  const statusColor = script ? (STATUS_COLOR[script.status] ?? 'var(--text-3)') : 'var(--text-3)'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 0 }}>
      {/* Back + header */}
      <div style={{ marginBottom: 20 }}>
        <Link to={`/projects/${projectId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-2)', fontSize: 13, marginBottom: 14, transition: 'color 0.15s' }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-2)')}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
          返回分集列表
        </Link>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <h1 className="page-title">
              {episode ? `第 ${episode.episode_number} 集 · ${episode.title}` : `第 ${episodeId} 集`}
            </h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4 }}>
              {script && (
                <>
                  <span style={{ fontSize: 12, color: statusColor, fontWeight: 600 }}>● {script.status}</span>
                  <span style={{ color: 'var(--text-3)' }}>·</span>
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>v{script.version}</span>
                </>
              )}
            </div>
            {episode?.synopsis && (
              <div style={{
                marginTop: 8, fontSize: 12, color: 'var(--text-2)',
                padding: '8px 12px', background: 'var(--bg-3)',
                borderRadius: 'var(--radius-sm)', maxWidth: 560,
                borderLeft: '3px solid var(--accent)',
              }}>
                {episode.synopsis}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn btn-ghost" onClick={handleGenerate} disabled={generating}>
              {generating ? (
                <><span className="spinner" style={{ width: 13, height: 13 }} /> 生成中…</>
              ) : (
                <><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 8v4l3 3"/><circle cx="18" cy="6" r="3"/></svg>AI 生成</>
              )}
            </button>
            <button className="btn btn-primary" onClick={handleSave}>
              {saved ? (
                <><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M20 6L9 17l-5-5"/></svg>已保存</>
              ) : (
                <><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>保存</>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 16, borderBottom: '1px solid var(--border)', paddingBottom: 0 }}>
        {(['editor', 'prompt'] as const).map((tab) => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={{
            padding: '8px 16px',
            background: 'none',
            border: 'none',
            borderBottom: `2px solid ${activeTab === tab ? 'var(--accent)' : 'transparent'}`,
            color: activeTab === tab ? 'var(--accent)' : 'var(--text-2)',
            fontWeight: activeTab === tab ? 600 : 400,
            fontSize: 13,
            cursor: 'pointer',
            transition: 'all 0.15s',
            marginBottom: -1,
          }}>
            {tab === 'editor' ? '剧本内容' : 'AI 提示词'}
          </button>
        ))}
      </div>

      {/* Editor area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {activeTab === 'editor' ? (
          <textarea
            className="textarea mono"
            value={content}
            onChange={e => setContent(e.target.value)}
            placeholder="在此编写剧本内容…&#10;&#10;场景一：&#10;（内景 咖啡厅 — 白天）&#10;&#10;人物A：（微笑）你好，我们约好了的。"
            style={{ flex: 1, minHeight: 480, resize: 'none' }}
          />
        ) : (
          <div>
            <p style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 10 }}>
              描述这一集的剧情方向、人物关系、情绪基调，AI 将根据提示词生成剧本草稿。
            </p>
            <textarea
              className="textarea"
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              rows={10}
              placeholder="例：第一集，男女主角在咖啡厅初次相遇，产生误会，气氛轻松幽默，结尾留悬念…"
            />
          </div>
        )}
      </div>
    </div>
  )
}
