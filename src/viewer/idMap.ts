/**
 * Stable splat identity across compaction (KTD3, docs/plans/2026-07-05-001).
 *
 * SparkJS compact-writes shift packed indices on every edit, so the viewer
 * keeps a parallel map: packed index → original splat ID (0..N-1 at load).
 * Selection results and backend edit requests speak original IDs; the backend
 * masks by ID against its alive mask.
 *
 * The backing array is allocated once at the original N and never resized —
 * compaction writes in place with writeIdx <= readIdx, which is safe for the
 * same reason the PackedSplats compact loop is.
 */
export class IdMap {
  private map: Uint32Array
  private live: number

  /**
   * `init` as a number builds the identity map 0..N-1 (fresh local load);
   * as an array it adopts explicit original IDs (backend-driven reload,
   * where packed index i corresponds to the backend's i-th alive Gaussian).
   */
  constructor(init: number | ArrayLike<number>) {
    if (typeof init === 'number') {
      this.map = new Uint32Array(init)
      for (let i = 0; i < init; i++) this.map[i] = i
      this.live = init
    } else {
      this.map = Uint32Array.from(init)
      this.live = this.map.length
    }
  }

  get liveCount(): number {
    return this.live
  }

  /** Original splat ID at a packed index. */
  idAt(packedIndex: number): number {
    return this.map[packedIndex]
  }

  /** Mirror one compact-write step: the splat at readIdx survives at writeIdx. */
  retain(writeIdx: number, readIdx: number): void {
    this.map[writeIdx] = this.map[readIdx]
  }

  /** Called after a compact pass with the new live count. */
  setLive(n: number): void {
    this.live = n
  }

  /** Copy of the live original-ID list (what the backend edit path consumes). */
  liveIds(): Uint32Array {
    return this.map.slice(0, this.live)
  }

  snapshot(): { data: Uint32Array; live: number } {
    return { data: this.map.slice(0, this.live), live: this.live }
  }

  /** Restore a snapshot taken before an edit (undo symmetry with the splat buffer). */
  restore(snap: { data: Uint32Array; live: number }): void {
    this.map.set(snap.data)
    this.live = snap.live
  }
}
