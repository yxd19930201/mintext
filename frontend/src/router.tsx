import { createBrowserRouter } from 'react-router-dom'
import Layout from './components/Layout'
import ProjectList from './pages/ProjectList'
import ProjectDetail from './pages/ProjectDetail'
import ScriptEditor from './pages/ScriptEditor'
import NovelList from './pages/NovelList'
import NovelDetail from './pages/NovelDetail'
import ChapterEditor from './pages/ChapterEditor'
import NovelToScript from './pages/NovelToScript'
import Settings from './pages/Settings'

function Placeholder({ title }: { title: string }) {
  return (
    <div style={{ maxWidth: 600 }}>
      <h1 className="page-title">{title}</h1>
      <p className="page-subtitle" style={{ marginTop: 8 }}>功能开发中，敬请期待。</p>
    </div>
  )
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <ProjectList /> },
      { path: 'projects/:projectId', element: <ProjectDetail /> },
      { path: 'projects/:projectId/episodes/:episodeId/script', element: <ScriptEditor /> },
      { path: 'novels', element: <NovelList /> },
      { path: 'novels/:novelId', element: <NovelDetail /> },
      { path: 'novels/:novelId/chapters/:chapterId', element: <ChapterEditor /> },
      { path: 'conversion', element: <NovelToScript /> },
      { path: 'ai', element: <Placeholder title="AI 助手" /> },
      { path: 'settings', element: <Settings /> },
    ],
  },
])
