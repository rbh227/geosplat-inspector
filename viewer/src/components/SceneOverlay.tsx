export default function SceneOverlay({ sceneName }: { sceneName: string }) {
  return (
    <>
      <div className="pointer-events-none fixed top-4 left-4 z-10 select-none rounded-md bg-black/50 px-3 py-1.5 font-mono text-xs text-white/90 backdrop-blur-sm">
        {sceneName}
      </div>
      <div className="pointer-events-none fixed bottom-4 right-4 z-10 select-none rounded-md bg-black/50 px-3 py-2 font-mono text-xs leading-relaxed text-white/80 backdrop-blur-sm">
        <div>
          <span className="text-white/50">drag</span> orbit
        </div>
        <div>
          <span className="text-white/50">right-drag</span> pan
        </div>
        <div>
          <span className="text-white/50">scroll</span> zoom
        </div>
      </div>
    </>
  );
}
