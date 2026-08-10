import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { scriptApi } from '../services/api/scriptApi'
import { episodeApi } from '../services/api/episodeApi'
import { aiApi } from '../services/api/aiApi'
import { conversionApi } from '../services/api/conversionApi'
import { exportTxt } from '../utils/export'
import type { Script, Episode } from '../types/models'
import { usePersistentState } from '../stores/persistentTaskStore'

const STATUS_COLOR: Record<string, string> = {
  draft: 'var(--text-2)',
  generated: 'var(--success)',
  reviewed: 'var(--accent)',
}

export default function ScriptEditor() {
  const { projectId, episodeId } = useParams<{ projectId: string; episodeId: string }>()
  const epId = Number(episodeId)
  const [episode, setEpisode] = useState<Episode | null>(null)
  const [script, setScript] = usePersistentState<Script | null>(`script:${episodeId}:data`, null)
  const [content, setContent] = usePersistentState(`script:${episodeId}:content`, '')
  const [prompt, setPrompt] = usePersistentState(`script:${episodeId}:prompt`, '')
  const [storyboard, setStoryboard] = usePersistentState(`script:${episodeId}:storyboard`, '')
  const [generating, setGenerating] = usePersistentState(`script:${episodeId}:generating`, false)
  const [generatingStoryboard, setGeneratingStoryboard] = usePersistentState(`script:${episodeId}:generatingStoryboard`, false)
  const [saved, setSaved] = useState(false)
  const [activeTab, setActiveTab] = useState<'editor' | 'storyboard'>('editor')

  useEffect(() => {
    episodeApi.get(Number(projectId), epId).then(res => setEpisode(res.data!))
    scriptApi.list(epId).then((res) => {
      if (res.data.length > 0) {
        setScript(res.data[0])
        setContent(res.data[0].content ?? '')
        const stored = res.data[0].ai_prompt ?? ''
        if (stored.startsWith('__STORYBOARD__\n')) {
          setStoryboard(stored.slice('__STORYBOARD__\n'.length))
          setPrompt('')
        } else {
          setPrompt(stored)
        }
      }
    })
  }, [epId, projectId])

  const handleSave = async () => {
    if (script) {
      const res = await scriptApi.update(epId, script.id, { content, ai_prompt: storyboard ? `__STORYBOARD__\n${storyboard}` : prompt })
      setScript(res.data!)
    } else {
      const res = await scriptApi.create(epId, { content, ai_prompt: storyboard ? `__STORYBOARD__\n${storyboard}` : prompt })
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

  const handleGenerateStoryboard = async () => {
    if (!content.trim()) return
    setGeneratingStoryboard(true)
    try {
      const res = await conversionApi.scriptToVideo({ script_text: content })
      const text = (res.data?.scenes || []).map(scene => [
        `【镜头 ${scene.scene_number}】`,
        `画面：${scene.description}`,
        `时长：${scene.duration}`,
        `镜头：${scene.camera_angle}`,
        `光线：${scene.lighting}`,
      ].join('\n')).join('\n\n')
      setStoryboard(text)
      setActiveTab('storyboard')
      if (script) {
        const updated = await scriptApi.update(epId, script.id, { ai_prompt: `__STORYBOARD__\n${text}` })
        setScript(updated.data!)
      }
    } catch (e) {
      alert('生成分镜失败：' + String(e))
    } finally {
      setGeneratingStoryboard(false)
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
            <button className="btn btn-ghost" onClick={() => {
              const filename = episode ? `第${episode.episode_number}集_${episode.title}` : `第${episodeId}集`
              exportTxt(activeTab === 'storyboard' ? storyboard : content, `${filename}_${activeTab === 'storyboard' ? '分镜脚本' : '短剧剧本'}`)
            }} disabled={activeTab === 'storyboard' ? !storyboard : !content}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              导出
            </button>
            <button className="btn btn-ghost" onClick={handleGenerateStoryboard} disabled={generatingStoryboard || !content.trim()}>
              {generatingStoryboard ? (
                <><span className="spinner" style={{ width: 13, height: 13 }} /> 生成分镜中…</>
              ) : '生成分镜脚本'}
            </button>
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
        {(['editor', 'storyboard'] as const).map((tab) => (
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
            {tab === 'editor' ? '短剧剧本' : '分镜脚本'}
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
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            {!storyboard && (
              <p style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 10 }}>
                本集还没有分镜脚本，请点击右上角“生成分镜脚本”。
              </p>
            )}
            <textarea
              className="textarea mono"
              value={storyboard}
              onChange={e => setStoryboard(e.target.value)}
              placeholder="生成后的分镜脚本将在这里展示…"
              style={{ flex: 1, minHeight: 480, resize: 'none' }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
