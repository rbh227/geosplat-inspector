'use client';

import { useEffect, useRef } from 'react';

type Viewer = {
  addSplatScene: (path: string, options?: Record<string, unknown>) => Promise<void>;
  start: () => void;
  stop?: () => void;
  dispose?: () => void;
};

export default function SplatViewer() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let viewer: Viewer | null = null;
    let cancelled = false;

    (async () => {
      const GaussianSplats3D = await import('@mkkellogg/gaussian-splats-3d');
      if (cancelled) return;

      viewer = new GaussianSplats3D.Viewer({
        rootElement: container,
        cameraUp: [0, 1, 0],
        sphericalHarmonicsDegree: 2,
      }) as Viewer;

      try {
        await viewer.addSplatScene('/scene2.ply', {
          splatAlphaRemovalThreshold: 20,
          showLoadingUI: true,
        });
        if (cancelled) return;
        viewer.start();
      } catch (err) {
        console.error('Failed to load splat:', err);
      }
    })();

    return () => {
      cancelled = true;
      if (viewer) {
        try {
          viewer.stop?.();
          viewer.dispose?.();
        } catch (err) {
          console.warn('Viewer cleanup error:', err);
        }
      }
      while (container.firstChild) {
        container.removeChild(container.firstChild);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{ position: 'fixed', inset: 0, width: '100vw', height: '100vh' }}
    />
  );
}
