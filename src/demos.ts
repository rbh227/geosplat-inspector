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
    name: 'Clean sphere',
    description: '1,000 well-behaved Gaussians',
    file: 'clean.ply',
    url: '/demos/clean.ply',
  },
  {
    name: 'Messy sphere',
    description: 'Floaters, outliers & needles to clean up',
    file: 'messy.ply',
    url: '/demos/messy.ply',
  },
  {
    name: 'Train yard',
    description: 'Real outdoor capture · 668K splats, floaters to clean',
    file: 'train.ply',
    url: '/demos/train.ply',
  },
  {
    name: 'Playroom',
    description: 'Building interior · 1.5M splats (heavier on CPU)',
    file: 'playroom.ply',
    url: '/demos/playroom.ply',
  },
  {
    name: 'Bonsai',
    description: 'Real-world capture (view only)',
    file: 'bonsai.splat',
    url: '/bonsai.splat',
  },
]
