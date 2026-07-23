import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { conversionApi } from '../services/api/conversionApi'
import { projectApi } from '../services/api/projectApi'
import { episodeApi } from '../services/api/episodeApi'
import { scriptApi } from '../services/api/scriptApi'
import { novelApi } from '../services/api/novelApi'
import { chapterApi } from '../services/api/chapterApi'
import { novelAiApi } from '../services/api/novelAiApi'
import { transport } from '../services/api'
import { exportTxt } from '../utils/export'
import type { Chapter, ChapterContent, ConversionEpisode, Novel, VideoScriptScene } from '../types/models'
import { usePersistentState } from '../stores/persistentTaskStore'

export default function NovelToScript() {
  const navigate = useNavigate()
  const [novelText, setNovelText] = usePersistentState('conversion:novelText', '')
  const [targetEpisodes, setTargetEpisodes] = usePersistentState('conversion:targetEpisodes', 5)
  const [style, setStyle] = usePersistentState('conversion:style', '')
  const [converting, setConverting] = usePersistentState('conversion:converting', false)
  const [episodes, setEpisodes] = usePersistentState<ConversionEpisode[]>('conversion:episodes', [])
  const [selectedEpisode, setSelectedEpisode] = usePersistentState<ConversionEpisode | null>('conversion:selectedEpisode', null)
  const [videoScenes, setVideoScenes] = usePersistentState<VideoScriptScene[]>('conversion:videoScenes', [])
  const [convertingToVideo, setConvertingToVideo] = usePersistentState('conversion:convertingToVideo', false)
  const [convertingEpisodeNumber, setConvertingEpisodeNumber] = usePersistentState<number | null>('conversion:convertingEpisodeNumber', null)
  const [saving, setSaving] = useState(false)
  const [novels, setNovels] = useState<Novel[]>([])
  const [sourceNovelId, setSourceNovelId] = usePersistentState('conversion:sourceNovelId', '')
  const [chapters, setChapters] = usePersistentState<Chapter[]>('conversion:chapters', [])
  const [hiddenChapterCount, setHiddenChapterCount] = usePersistentState('conversion:hiddenChapterCount', 0)
  const [selectedChapterIds, setSelectedChapterIds] = usePersistentState<Set<number>>('conversion:selectedChapterIds', new Set())
  const [importing, setImporting] = usePersistentState('conversion:importing', false)
  const [storyboards, setStoryboards] = usePersistentState<Record<number, VideoScriptScene[]>>('conversion:storyboards', {})
  const [storyboardProgress, setStoryboardProgress] = usePersistentState<{ done: number; total: number } | null>('conversion:storyboardProgress', null)

  const formatStoryboard = (scenes: VideoScriptScene[]) => scenes.map(scene => [
    `【镜头 ${scene.scene_number}】`,
    `画面：${scene.description}`,
    `时长：${scene.duration}`,
    `镜头：${scene.camera_angle}`,
    `光线：${scene.lighting}`,
  ].join('\n')).join('\n\n')

  useEffect(() => {
    novelApi.list(0, 200).then(res => setNovels(res.data || [])).catch(() => setNovels([]))
  }, [])

  const handleSelectNovel = async (value: string) => {
    setSourceNovelId(value)
    setSelectedChapterIds(new Set())
    setChapters([])
    setHiddenChapterCount(0)
    if (!value) return
    try {
      const [allRes, contentRes] = await Promise.all([
        chapterApi.list(Number(value)),
        novelAiApi.getChaptersWithContent(Number(value)),
      ])
      const allChapters = allRes.data || []
      const contentIds = new Set((contentRes.data || []).map(chapter => chapter.id))
      const available = allChapters.filter(chapter => contentIds.has(chapter.id))
      setChapters(available)
      setHiddenChapterCount(allChapters.length - available.length)
    } catch (e) {
      alert('加载章节失败: ' + String(e))
    }
  }

  const handleImportChapters = async () => {
    if (!sourceNovelId || selectedChapterIds.size === 0) {
      alert('请先选择小说和章节')
      return
    }
    setImporting(true)
    try {
      const selected = chapters
        .filter(chapter => selectedChapterIds.has(chapter.id))
        .sort((a, b) => a.chapter_number - b.chapter_number)
      const parts: string[] = []
      for (const chapter of selected) {
        const res = await transport.get<{ success: boolean; data: ChapterContent | null }>(
          `/novels/${sourceNovelId}/chapters/${chapter.id}/content`,
        )
        const content = res.data?.content?.trim()
        if (content) parts.push(`第${chapter.chapter_number}章 ${chapter.title}\n${content}`)
      }
      if (parts.length === 0) {
        alert('所选章节还没有正文内容，请先生成或编辑章节正文')
        return
      }
      const imported = parts.join('\n\n')
      if (imported.length > 50000) {
        alert('所选章节正文超过 50000 字，请减少选择的章节数量')
        return
      }
      setNovelText(imported)
      setEpisodes([])
      setStoryboards({})
      alert(`已导入 ${parts.length} 章，共 ${imported.length} 字`)
    } catch (e) {
      alert('导入章节失败: ' + String(e))
    } finally {
      setImporting(false)
    }
  }

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
    setConvertingEpisodeNumber(episode.episode_number)
    try {
      const res = await conversionApi.scriptToVideo({
        script_text: episode.script,
      })
      if (res.data) {
        setVideoScenes(res.data.scenes)
        setStoryboards(prev => ({ ...prev, [episode.episode_number]: res.data!.scenes }))
        setSelectedEpisode(episode)
        alert(`转换成功！生成了 ${res.data.scenes.length} 个视频场景`)
      }
    } catch (e) {
      alert('转换失败: ' + String(e))
    } finally {
      setConvertingToVideo(false)
    }
  }

  const handleConvertAllToStoryboards = async () => {
    if (episodes.length === 0) return
    setConvertingToVideo(true)
    setStoryboardProgress({ done: 0, total: episodes.length })
    try {
      const all: Record<number, VideoScriptScene[]> = {}
      for (let index = 0; index < episodes.length; index += 1) {
        const episode = episodes[index]
        const res = await conversionApi.scriptToVideo({ script_text: episode.script })
        all[episode.episode_number] = res.data?.scenes || []
        setStoryboardProgress({ done: index + 1, total: episodes.length })
      }
      setStoryboards(all)
      const first = episodes[0]
      setSelectedEpisode(first)
      setVideoScenes(all[first.episode_number] || [])
      alert(`全部分镜生成完成，共 ${episodes.length} 集`)
    } catch (e) {
      alert('生成全部分镜失败: ' + String(e))
    } finally {
      setConvertingEpisodeNumber(null)
      setStoryboardProgress(null)
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
        const scenes = storyboards[ep.episode_number] || []
        await scriptApi.create(epRes.data!.id, {
          content: ep.script,
          ai_prompt: scenes.length > 0 ? `__STORYBOARD__\n${formatStoryboard(scenes)}` : undefined,
        })
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
        <p className="page-subtitle">选择已创作的小说章节，一键转换为短剧剧本，再一键生成分镜脚本</p>
      </div>

      {/* Step 1: Novel to Script */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div style={{ fontWeight: 600, marginBottom: 16, fontSize: 15 }}>步骤 1：选择小说章节</div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, marginBottom: 12 }}>
          <div>
            <label className="label">选择已创作的小说</label>
            <select className="input" value={sourceNovelId} onChange={e => handleSelectNovel(e.target.value)}>
              <option value="">请选择小说</option>
              {novels.map(novel => <option key={novel.id} value={novel.id}>{novel.title}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button className="btn btn-primary" onClick={handleImportChapters} disabled={importing || selectedChapterIds.size === 0}>
              {importing ? '导入中...' : `导入所选章节 (${selectedChapterIds.size})`}
            </button>
          </div>
        </div>

        {chapters.length > 0 && (
          <div style={{ border: '1px solid #34384b', borderRadius: 6, padding: 12, marginBottom: 16, maxHeight: 220, overflow: 'auto' }}>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, fontSize: 13 }}>
              <input
                type="checkbox"
                checked={selectedChapterIds.size === chapters.length}
                onChange={e => setSelectedChapterIds(e.target.checked ? new Set(chapters.map(chapter => chapter.id)) : new Set())}
              />
              全选全部章节
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
              {chapters.map(chapter => (
                <label key={chapter.id} style={{ display: 'flex', gap: 7, alignItems: 'center', fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={selectedChapterIds.has(chapter.id)}
                    onChange={e => setSelectedChapterIds(prev => {
                      const next = new Set(prev)
                      e.target.checked ? next.add(chapter.id) : next.delete(chapter.id)
                      return next
                    })}
                  />
                  第 {chapter.chapter_number} 章：{chapter.title}
                </label>
              ))}
            </div>
          </div>
        )}

        {sourceNovelId && chapters.length === 0 && (
          <div style={{ border: '1px solid #7c5b24', background: '#2a2418', color: '#e8c77a', borderRadius: 6, padding: 12, marginBottom: 16, fontSize: 13 }}>
            该小说目前只有章节大纲，没有已生成的章节正文。请先进入“小说创作”生成具体章节内容，再进行短剧转换。
          </div>
        )}

        {chapters.length > 0 && hiddenChapterCount > 0 && (
          <div style={{ color: 'var(--text-3)', fontSize: 12, marginTop: -8, marginBottom: 14 }}>
            仅显示已有正文的 {chapters.length} 个章节；另有 {hiddenChapterCount} 个仅含大纲的章节已隐藏。
          </div>
        )}

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
          <label className="label">已导入的小说正文（也可手动粘贴，最多 50000 字）</label>
          <textarea
            className="textarea"
            value={novelText}
            onChange={e => setNovelText(e.target.value)}
            rows={12}
            placeholder="从上方选择章节导入，或手动粘贴小说文本..."
            maxLength={50000}
            style={{ fontFamily: 'monospace', fontSize: 13, lineHeight: 1.8 }}
          />
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
            {novelText.length} / 50000 字
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
              <button className="btn btn-primary" onClick={handleConvertAllToStoryboards} disabled={convertingToVideo || convertingEpisodeNumber !== null}>
                {convertingToVideo && storyboardProgress
                  ? `生成分镜 ${storyboardProgress.done}/${storyboardProgress.total}...`
                  : '一键生成全部分镜'}
              </button>
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
              <div key={episode.episode_number} className="card" style={{ background: 'var(--bg-3)', borderColor: 'var(--border)', padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>
                      第 {episode.episode_number} 集：{episode.title}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>
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
                      onClick={() => {
                        const existing = storyboards[episode.episode_number]
                        if (existing) {
                          setSelectedEpisode(episode)
                          setVideoScenes(existing)
                        } else {
                          handleConvertToVideo(episode)
                        }
                      }}
                      disabled={convertingToVideo || convertingEpisodeNumber !== null}
                    >
                      {convertingEpisodeNumber === episode.episode_number
                        ? '转换中...'
                        : storyboards[episode.episode_number]
                          ? '查看分镜'
                          : '生成本集分镜'}
                    </button>
                  </div>
                </div>
                <div style={{
                  background: 'var(--bg-2)',
                  color: 'var(--text)',
                  border: '1px solid var(--border)',
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
              步骤 3：短剧分镜脚本
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
              导出分镜脚本
            </button>
          </div>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 16 }}>
            第 {selectedEpisode.episode_number} 集：{selectedEpisode.title} - 共 {videoScenes.length} 个场景
          </div>

          <div style={{ display: 'grid', gap: 12 }}>
            {videoScenes.map(scene => (
              <div key={scene.scene_number} className="card" style={{ background: 'var(--bg-3)', borderColor: 'var(--border)', padding: 14 }}>
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

                <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-2)' }}>
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

          <div style={{ marginTop: 16, padding: 12, background: '#242031', border: '1px solid var(--border)', borderRadius: 6, fontSize: 12, color: 'var(--text-2)' }}>
            分镜脚本已按场景拆分，可直接导出或复制用于后续拍摄和视频生成。
          </div>
        </div>
      )}

      {episodes.length === 0 && (
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
          请先选择小说章节导入，再点击「转换为短剧」开始
        </div>
      )}
    </div>
  )
}
