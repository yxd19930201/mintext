import { createHashRouter } from 'react-router-dom'
import Layout from './components/Layout'
import ProjectList from './pages/ProjectList'
import ProjectDetail from './pages/ProjectDetail'
import ScriptEditor from './pages/ScriptEditor'
import NovelList from './pages/NovelList'
import NovelDetail from './pages/NovelDetail'
import ChapterEditor from './pages/ChapterEditor'
import NovelToScript from './pages/NovelToScript'
import Settings from './pages/Settings'
import WorkCenter from './pages/WorkCenter'
import AIAssistant from './pages/AIAssistant'

// Hash routing works both on the Vite dev server and from Electron's file:// URL.
export const router = createHashRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <WorkCenter /> },
      { path: 'projects', element: <ProjectList /> },
      { path: 'projects/:projectId', element: <ProjectDetail /> },
      { path: 'projects/:projectId/episodes/:episodeId/script', element: <ScriptEditor /> },
      { path: 'novels', element: <NovelList /> },
      { path: 'novels/:novelId', element: <NovelDetail /> },
      { path: 'novels/:novelId/chapters/:chapterId', element: <ChapterEditor /> },
      { path: 'conversion', element: <NovelToScript /> },
      { path: 'ai', element: <AIAssistant /> },
      { path: 'settings', element: <Settings /> },
    ],
  },
])
