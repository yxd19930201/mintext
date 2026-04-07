import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { conversionApi } from '../services/api/conversionApi'
import { projectApi } from '../services/api/projectApi'
import { episodeApi } from '../services/api/episodeApi'
import { scriptApi } from '../services/api/scriptApi'
import { exportTxt } from '../utils/export'
import type { ConversionEpisode, VideoScriptScene } from '../types/models'

export default function NovelToScript() {
  const navigate = useNavigate()
  const [novelText, setNovelText] = useState('')
  const [targetEpisodes, setTargetEpisodes] = useState(5)
  const [style, setStyle] = useState('')
  const [converting, setConverting] = useState(false)
  const [episodes, setEpisodes] = useState<ConversionEpisode[]>([])
  const [selectedEpisode, setSelectedEpisode] = useState<ConversionEpisode | null>(null)
  const [videoScenes, setVideoScenes] = useState<VideoScriptScene[]>([])
  const [convertingToVideo, setConvertingToVideo] = useState(false)
  const [saving, setSaving] = useState(false)

  const handleConvertToScript = async () => {
    if (!novelText.trim()) {
      alert('请输入小说文本')
      return
    }

    setConverting(true)
    try {
      const res = await conversionApi.novelToScript({
        novel_text: novelText,
        target_episodes: targetEpisodes,
        style: style || undefined,
      })
      if (res.data) {
        setEpisodes(res.data.episodes)
        alert(`转换成功！生成了 ${res.data.total_episodes} 集短剧`)
      }
    } catch (e) {
      alert('转换失败: ' + String(e))
    } finally {
      setConverting(false)
    }
  }

  const handleConvertToVideo = async (episode: ConversionEpisode) => {
    setConvertingToVideo(true)
    try {
      const res = await conversionApi.scriptToVideo({
        script_text: episode.script,
      })
      if (res.data) {
        setVideoScenes(res.data.scenes)
        setSelectedEpisode(episode)
        alert(`转换成功！生成了 ${res.data.scenes.length} 个视频场景`)
      }
    } catch (e) {
      alert('转换失败: ' + String(e))
    } finally {
      setConvertingToVideo(false)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    alert('已复制到剪贴板')
  }

  const handleSaveToProject = async () => {
    if (episodes.length === 0) return
    setSaving(true)
    try {
      const projRes = await projectApi.create({
        title: `短剧项目 ${new Date().toLocaleDateString('zh-CN')}`,
        synopsis: novelText.slice(0, 500),
        total_episodes: episodes.length,
      })
      const projectId = projRes.data!.id
      for (const ep of episodes) {
        const epRes = await episodeApi.create(projectId, {
          title: ep.title,
          episode_number: ep.episode_number,
          synopsis: ep.script.slice(0, 200),
        })
        await scriptApi.create(epRes.data!.id, { content: ep.script })
      }
      alert(`已保存为项目，共 ${episodes.length} 集`)
      navigate(`/projects/${projectId}`)
    } catch (e) {
      alert('保存失败: ' + String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 1200 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 className="page-title">小说转短剧</h1>
        <p className="page-subtitle">将小说文本转换为短剧剧本，并可进一步转换为视频生成脚本</p>
      </div>

      {/* Step 1: Novel to Script */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ fontWeight: 600, marginBottom: 16, fontSize: 15 }}>步骤 1：输入小说文本</div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 200px', gap: 12, marginBottom: 12 }}>
          <div>
            <label className="label">目标集数</label>
            <input
              className="input"
              type="number"
              min={1}
              max={20}
              value={targetEpisodes}
              onChange={e => setTargetEpisodes(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="label">风格（可选）</label>
            <input
              className="input"
              value={style}
              onChange={e => setStyle(e.target.value)}
              placeholder="例：悬疑、爱情、喜剧"
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button
              className="btn btn-primary"
              onClick={handleConvertToScript}
              disabled={converting || !novelText.trim()}
              style={{ width: '100%' }}
            >
              {converting ? '转换中...' : '转换为短剧'}
            </button>
          </div>
        </div>

        <div>
          <label className="label">小说文本（支持 5000 字）</label>
          <textarea
            className="textarea"
            value={novelText}
            onChange={e => setNovelText(e.target.value)}
            rows={12}
            placeholder="粘贴小说文本，最多 5000 字..."
            maxLength={5000}
            style={{ fontFamily: 'monospace', fontSize: 13, lineHeight: 1.8 }}
          />
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
            {novelText.length} / 5000 字
          </div>
        </div>
      </div>

      {/* Step 2: Script Results */}
      {episodes.length > 0 && (
        <div className="card" style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ fontWeight: 600, fontSize: 15 }}>
              步骤 2：短剧剧本（共 {episodes.length} 集）
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                className="btn btn-primary"
                onClick={handleSaveToProject}
                disabled={saving}
              >
                {saving ? '保存中...' : '保存到项目'}
              </button>
              <button
                className="btn btn-ghost"
                onClick={() => {
                  const lines: string[] = []
                  episodes.forEach(ep => {
                    lines.push(`=== 第 ${ep.episode_number} 集：${ep.title} ===`)
                    lines.push(`预计时长：${ep.duration_estimate}`, ``)
                    lines.push(ep.script, ``)
                  })
                  exportTxt(lines.join('\n'), '短剧剧本')
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                导出全部剧本
              </button>
            </div>
          </div>

          <div style={{ display: 'grid', gap: 16 }}>
            {episodes.map(episode => (
              <div key={episode.episode_number} className="card" style={{ background: '#fafafa', padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>
                      第 {episode.episode_number} 集：{episode.title}
                    </div>
                    <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
                      预计时长：{episode.duration_estimate}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      className="btn btn-sm"
                      onClick={() => copyToClipboard(episode.script)}
                    >
                      复制剧本
                    </button>
                    <button
                      className="btn btn-sm"
                      onClick={() => exportTxt(episode.script, `第${episode.episode_number}集_${episode.title}`)}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                      导出
                    </button>
                    <button
                      className="btn btn-sm btn-primary"
                      onClick={() => handleConvertToVideo(episode)}
                      disabled={convertingToVideo}
                    >
                      {convertingToVideo ? '转换中...' : '转为视频脚本'}
                    </button>
                  </div>
                </div>
                <div style={{
                  background: '#fff',
                  padding: 12,
                  borderRadius: 6,
                  fontSize: 13,
                  lineHeight: 1.8,
                  whiteSpace: 'pre-wrap',
                  fontFamily: 'monospace',
                  maxHeight: 300,
                  overflow: 'auto',
                }}>
                  {episode.script}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Step 3: Video Script */}
      {videoScenes.length > 0 && selectedEpisode && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ fontWeight: 600, fontSize: 15 }}>
              步骤 3：Seedance 2.0 视频生成脚本
            </div>
            <button
              className="btn btn-ghost"
              onClick={() => {
                const lines: string[] = [
                  `=== 第 ${selectedEpisode.episode_number} 集：${selectedEpisode.title} ===`,
                  `视频脚本 · 共 ${videoScenes.length} 个场景`, ``
                ]
                videoScenes.forEach(sc => {
                  lines.push(`【场景 ${sc.scene_number}】`)
                  lines.push(`描述：${sc.description}`)
                  lines.push(`时长：${sc.duration}  镜头：${sc.camera_angle}  光线：${sc.lighting}`, ``)
                })
                exportTxt(lines.join('\n'), `第${selectedEpisode.episode_number}集_视频脚本`)
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              导出视频脚本
            </button>
          </div>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 16 }}>
            第 {selectedEpisode.episode_number} 集：{selectedEpisode.title} - 共 {videoScenes.length} 个场景
          </div>

          <div style={{ display: 'grid', gap: 12 }}>
            {videoScenes.map(scene => (
              <div key={scene.scene_number} className="card" style={{ background: '#f0f9ff', padding: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>
                    场景 {scene.scene_number}
                  </div>
                  <button
                    className="btn btn-sm"
                    onClick={() => copyToClipboard(scene.description)}
                    style={{ padding: '2px 8px', fontSize: 11 }}
                  >
                    复制
                  </button>
                </div>

                <div style={{ fontSize: 13, lineHeight: 1.7, marginBottom: 10 }}>
                  {scene.description}
                </div>

                <div style={{ display: 'flex', gap: 16, fontSize: 12, color: '#666' }}>
                  <div>
                    <span style={{ fontWeight: 600 }}>时长：</span>{scene.duration}
                  </div>
                  <div>
                    <span style={{ fontWeight: 600 }}>镜头：</span>{scene.camera_angle}
                  </div>
                  <div>
                    <span style={{ fontWeight: 600 }}>光线：</span>{scene.lighting}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 16, padding: 12, background: '#fffbeb', borderRadius: 6, fontSize: 12, color: '#92400e' }}>
            💡 提示：将每个场景描述复制到 Seedance 2.0 模型中生成视频，按顺序拼接即可完成短剧视频制作
          </div>
        </div>
      )}

      {episodes.length === 0 && (
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
          输入小说文本并点击「转换为短剧」开始
        </div>
      )}
    </div>
  )
}
