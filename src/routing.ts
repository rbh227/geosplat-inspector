/**
 * Hash routing for the two pages (editor, analyst).
 *
 * Hash rather than path on purpose: a path route needs react-router plus
 * SPA-fallback config on the dev server and on any static host. This needs
 * neither, and swapping in a real router later is mechanical.
 */
import { useEffect, useState } from 'react'

export type Route =
  | { page: 'editor'; sceneId: null }
  | { page: 'analyst'; sceneId: string | null }

const EDITOR: Route = { page: 'editor', sceneId: null }

export function parseRoute(hash: string): Route {
  const [path, query] = hash.replace(/^#/, '').split('?')
  if (path !== '/analyze') return EDITOR
  const scene = new URLSearchParams(query ?? '').get('scene')
  return { page: 'analyst', sceneId: scene || null }
}

/** Href for the analyst window on a given backend scene. */
export function analystHref(sceneId: string): string {
  return `#/analyze?scene=${encodeURIComponent(sceneId)}`
}

/** Current route, re-evaluated on every hashchange. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
