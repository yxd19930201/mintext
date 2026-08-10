import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useNovelStore } from '../stores/novelStore'
import { useProjectStore } from '../stores/projectStore'
import { usePersistentTaskValues } from '../stores/persistentTaskStore'
import { chapterApi } from '../services/api/chapterApi'
import { episodeApi } from '../services/api/episodeApi'
import { novelAiApi } from '../services/api/novelAiApi'
import { scriptApi } from '../services/api/scriptApi'

interface DashboardStats {
  outlinedChapters: number
  generatedChapters: number
  syncedEpisodes: number
}

interface WorkProgressItem {
  key: string
  type: 'novel' | 'drama'
  title: string
  completed: number
  total: number
  percent: number
  stage: string
  to: string
}

export default function WorkCenter() {
  const { novels, fetchNovels } = useNovelStore()
  const { projects, fetchProjects } = useProjectStore()
  const taskValues = usePersistentTaskValues()
  const [stats, setStats] = useState<DashboardStats>({ outlinedChapters: 0, generatedChapters: 0, syncedEpisodes: 0 })
  const [workProgress, setWorkProgress] = useState<WorkProgressItem[]>([])

  useEffect(() => {
    void Promise.all([fetchNovels(), fetchProjects()])
  }, [fetchNovels, fetchProjects])

  useEffect(() => {
    let cancelled = false
    const loadStats = async () => {
      const novelResults = await Promise.all(novels.map(async novel => {
        const [chapters, contents] = await Promise.allSettled([chapterApi.list(novel.id), novelAiApi.getChaptersWithContent(novel.id)])
        const outlined = chapters.status === 'fulfilled' ? chapters.value.data?.length || 0 : 0
        const generated = contents.status === 'fulfilled' ? contents.value.data?.length || 0 : 0
        const total = Math.max(novel.total_chapters || 0, outlined, 1)
        const percent = Math.min(100, Math.round(generated / total * 100))
        return { outlined, generated, item: { key: `novel-${novel.id}`, type: 'novel' as const, title: novel.title, completed: generated, total, percent, stage: percent === 0 ? '未开始' : percent === 100 ? '已完成' : '正文创作中', to: `/novels/${novel.id}` } }
      }))
      const projectResults = await Promise.all(projects.map(async project => {
        const episodeResponse = await episodeApi.list(project.id).catch(() => null)
        const episodes = episodeResponse?.data || []
        const scriptResults = await Promise.allSettled(episodes.map(episode => scriptApi.list(episode.id)))
        const generated = scriptResults.reduce((sum, result) => sum + (result.status === 'fulfilled' && result.value.data.some(script => Boolean(script.content?.trim())) ? 1 : 0), 0)
        const total = Math.max(project.total_episodes || 0, episodes.length, 1)
        const percent = Math.min(100, Math.round(generated / total * 100))
        return { episodes: episodes.length, item: { key: `drama-${project.id}`, type: 'drama' as const, title: project.title, completed: generated, total, percent, stage: percent === 0 ? '未开始' : percent === 100 ? '已完成' : '剧本生成中', to: `/projects/${project.id}` } }
      }))
      if (cancelled) return
      setStats({
        outlinedChapters: novelResults.reduce((sum, result) => sum + result.outlined, 0),
        generatedChapters: novelResults.reduce((sum, result) => sum + result.generated, 0),
        syncedEpisodes: projectResults.reduce((sum, result) => sum + result.episodes, 0),
      })
      setWorkProgress([...novelResults.map(result => result.item), ...projectResults.map(result => result.item)])
    }
    void loadStats()
    return () => { cancelled = true }
  }, [novels, projects])

  const taskOverview = useMemo(() => {
    const entries = Object.entries(taskValues)
    const activeKeys = entries.filter(([key, value]) => value === true && /(generating|converting|importing|syncing|rebuilding)/i.test(key))
    const progress = entries.find(([key, value]) => /Progress$/i.test(key) && value && typeof value === 'object')?.[1] as { done?: number; total?: number } | undefined
    const labelFor = (key: string) => key.startsWith('conversion:') ? '小说正在改编为短剧' : key.includes('rebuild') ? '正在更新故事档案' : key.includes('sync') ? '正在同步作品结构' : key.startsWith('script:') ? '正在生成短剧或分镜' : '正在生成小说内容'
    return { count: activeKeys.length, label: activeKeys[0] ? labelFor(activeKeys[0][0]) : '当前没有运行中的生成任务', progress }
  }, [taskValues])

  const latestWork = [...novels, ...projects].sort((a, b) => new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime())[0]

  return (
    <div className="work-center">
      <section className="work-hero">
        <div>
          <span className="work-eyebrow">青玉书房 · 作品总览</span>
          <h1 className="page-title">让故事从灵感，走到可拍摄的画面</h1>
          <p className="page-subtitle">小说、短剧与分镜不再是分散的工具，而是一条清晰、可追溯的创作路径。</p>
        </div>
        <div className="work-hero-actions">
          <Link className="btn btn-ghost" to="/novels">进入小说书架</Link>
          <Link className="btn btn-primary" to="/conversion">开始改编</Link>
        </div>
      </section>

      <section className="work-flow" aria-label="创作流程">
        {[
          ['01', '小说正文', '世界观、人物与章节'],
          ['02', '短剧剧本', '选章导入，一键改编'],
          ['03', '分镜脚本', '在短剧项目中生成'],
          ['04', '成品导出', '沉淀并交付作品'],
        ].map(([index, title, desc], i) => (
          <div className="work-flow-step" key={title}>
            <span className="work-flow-index">{index}</span>
            <div><strong>{title}</strong><small>{desc}</small></div>
            {i < 3 && <span className="work-flow-arrow">→</span>}
          </div>
        ))}
      </section>

      <div className="work-category-grid">
        <Link className="work-category-card novels" to="/novels">
          <div className="work-category-seal">文</div>
          <div className="work-category-copy">
            <span>长篇创作</span><h2>小说书架</h2>
            <p>从故事梗概、大纲到连续正文，用路线图和状态账本保持创作连贯。</p>
          </div>
          <div className="work-category-footer"><b>{novels.length}</b> 部作品 <span>查看小说 →</span></div>
        </Link>
        <Link className="work-category-card scripts" to="/projects">
          <div className="work-category-seal">剧</div>
          <div className="work-category-copy">
            <span>视觉叙事</span><h2>短剧工坊</h2>
            <p>管理短剧分集、标准剧本和分镜脚本，承接小说改编后的制作流程。</p>
          </div>
          <div className="work-category-footer"><b>{projects.length}</b> 个项目 <span>查看短剧 →</span></div>
        </Link>
      </div>

      <section className="work-project-section" aria-label="各项目创作进度">
        <div className="work-section-heading"><div><span>创作看板</span><h2>各项目进度</h2></div><small>每个作品独立计算，不相互混合</small></div>
        <div className="work-project-grid">
          {workProgress.map(item => (
            <Link className="work-project-progress" to={item.to} key={item.key}>
              <div className={`work-project-symbol ${item.type}`}>{item.type === 'novel' ? '文' : '剧'}</div>
              <div className="work-project-main">
                <div className="work-project-title"><div><span>{item.type === 'novel' ? '小说' : '短剧'} · {item.stage}</span><strong>{item.title}</strong></div><b>{item.percent}%</b></div>
                <div className="work-progress-track"><i style={{ width: `${item.percent}%` }} /></div>
                <div className="work-project-meta"><span>已完成 {item.completed} / {item.total} {item.type === 'novel' ? '章正文' : '集剧本'}</span><span>{item.percent === 0 ? '未开始 →' : item.percent === 100 ? '已完成' : '继续创作 →'}</span></div>
              </div>
            </Link>
          ))}
          {!workProgress.length && <div className="work-empty card">还没有可统计的作品，创建作品后将在这里显示独立进度。</div>}
        </div>
      </section>

      <section className="work-dashboard work-status-only" aria-label="当前任务状态">
        <div className={`work-status-panel${taskOverview.count ? ' is-running' : ''}`}>
          <span className="work-status-dot" />
          <div><small>当前状态</small><strong>{taskOverview.label}</strong>
            {taskOverview.progress?.total ? <p>已处理 {taskOverview.progress.done || 0} / {taskOverview.progress.total}</p> : <p>{taskOverview.count ? `${taskOverview.count} 项任务进行中` : '可以开始新的创作任务'}</p>}
          </div>
        </div>
      </section>

      <section className="work-next-step">
        <div className="work-next-icon">今</div>
        <div><span>今日建议</span><strong>{latestWork ? `继续完善《${latestWork.title}》` : '创建你的第一部作品'}</strong><p>{stats.outlinedChapters > stats.generatedChapters ? `还有 ${stats.outlinedChapters - stats.generatedChapters} 章已有大纲、等待生成正文。` : '先建立故事梗概与大纲，再进入连续正文创作。'}</p></div>
        <Link className="btn btn-primary" to={novels[0] ? `/novels/${novels[0].id}` : '/novels'}>继续创作</Link>
      </section>

      <section className="work-recent-section">
        <div className="work-section-heading"><div><span>近日案头</span><h2>最近创作</h2></div><Link to="/conversion">小说转短剧 →</Link></div>
        <div className="work-recent-grid">
          {novels.slice(0, 2).map(novel => (
            <Link className="work-recent-card" to={`/novels/${novel.id}`} key={`n-${novel.id}`}>
              <span className="work-card-type">小说</span><h3>{novel.title}</h3>
              <p>{novel.synopsis || '尚未填写故事梗概'}</p><small>{novel.genre || '未分类'} · {novel.total_chapters || 0} 章</small>
            </Link>
          ))}
          {projects.slice(0, 2).map(project => (
            <Link className="work-recent-card" to={`/projects/${project.id}`} key={`p-${project.id}`}>
              <span className="work-card-type drama">短剧</span><h3>{project.title}</h3>
              <p>{project.synopsis || project.description || '尚未填写项目简介'}</p><small>{project.genre || '未分类'} · {project.total_episodes || 0} 集</small>
            </Link>
          ))}
          {!novels.length && !projects.length && (
            <div className="work-empty card">案头尚空。先进入小说书架写下第一个故事，或创建一个短剧项目。</div>
          )}
        </div>
      </section>
    </div>
  )
}
