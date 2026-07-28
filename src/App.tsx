import { useRoute } from './routing'
import EditorPage from './pages/EditorPage'

export default function App() {
  const route = useRoute()
  if (route.page === 'analyst') {
    // The analyst page lands in a later task; until then the route falls back
    // to the editor so the build never references a component that does not
    // exist yet.
    return <EditorPage />
  }
  return <EditorPage />
}
