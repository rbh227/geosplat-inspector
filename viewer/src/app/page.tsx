import SceneOverlay from '@/components/SceneOverlay';
import SplatViewer from '@/components/SplatViewer';

export default function Home() {
  return (
    <>
      <SplatViewer />
      <SceneOverlay sceneName="scene2 · 30k iters" />
    </>
  );
}
