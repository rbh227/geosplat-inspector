/* -------------------------------------------------------------------------- */
/*  Undo stack for splat scene state                                          */
/* -------------------------------------------------------------------------- */

export interface UndoEntry {
  label: string
  data: Uint32Array
  numSplats: number
  timestamp: number
}

/**
 * A simple linear undo stack.  Stores snapshots of the raw splat buffer so
 * that destructive cleanup operations can be reversed.
 *
 * The stack has a configurable maximum size; the oldest entry is evicted when
 * the limit is exceeded.
 */
export class UndoStack {
  private stack: UndoEntry[] = []
  private maxSize: number

  constructor(maxSize = 10) {
    this.maxSize = maxSize
  }

  /**
   * Push a new snapshot onto the stack.
   * If the stack already holds `maxSize` entries the oldest one is removed.
   */
  push(label: string, data: Uint32Array, numSplats: number): void {
    if (this.stack.length >= this.maxSize) {
      this.stack.shift()
    }
    this.stack.push({
      label,
      data,
      numSplats,
      timestamp: Date.now(),
    })
  }

  /**
   * Pop and return the most recent snapshot, or `null` if the stack is empty.
   */
  pop(): UndoEntry | null {
    return this.stack.pop() ?? null
  }

  /**
   * Whether the stack contains at least one entry.
   */
  canUndo(): boolean {
    return this.stack.length > 0
  }

  /**
   * Peek at the top entry without removing it.
   */
  peek(): UndoEntry | null {
    if (this.stack.length === 0) return null
    return this.stack[this.stack.length - 1]
  }

  /**
   * Return the labels of all entries, oldest first.
   */
  getLabels(): string[] {
    return this.stack.map((e) => e.label)
  }

  /**
   * Remove all entries.
   */
  clear(): void {
    this.stack = []
  }

  /**
   * Number of entries currently on the stack.
   */
  get size(): number {
    return this.stack.length
  }
}
