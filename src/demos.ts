/**
 * Demo splats shown in the empty-state loader.
 *
 * To add more: drop a file in `public/demos/` (or `public/`) and add a row here.
 * `.ply` demos are uploaded to the backend so the agent can inspect/clean them;
 * other formats (.splat/.spz/.ksplat) render in the viewer but are view-only.
 */
export interface DemoSplat {
  /** Display name in the picker. */
  name: string
  /** One-line description. */
  description: string
  /** File name (extension decides whether the backend agent can use it). */
  file: string
  /** Served URL (same-origin: under public/). */
  url: string
}

export const DEMO_SPLATS: DemoSplat[] = [
  {
    name: 'House',
    description: 'Building capture · 420K splats',
    file: 'bldg01_house.ply',
    url: '/demos/bldg01_house.ply',
  },
  {
    name: 'Trailer',
    description: 'Full trailer capture · 500K splats',
    file: 'trailer_full.ply',
    url: '/demos/trailer_full.ply',
  },
  {
    name: 'Scene',
    description: 'Real capture · 1.3M splats',
    file: 'scene.ply',
    url: '/demos/scene.ply',
  },
  {
    name: 'Iona Park',
    description: 'Outdoor park capture · 2M splats (heavier on CPU)',
    file: 'iona_park.ply',
    url: '/demos/iona_park.ply',
  },
  {
    name: 'Raw capture',
    description: 'Uncleaned capture · 3M splats (heaviest on CPU)',
    file: 'raw.ply',
    url: '/demos/raw.ply',
  },
]
