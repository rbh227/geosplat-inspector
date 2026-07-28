import { useRoute } from './routing'
import EditorPage from './pages/EditorPage'
import AnalystPage from './pages/AnalystPage'

export default function App() {
  const route = useRoute()
  if (route.page === 'analyst') return <AnalystPage sceneId={route.sceneId} />
  return <EditorPage />
}
