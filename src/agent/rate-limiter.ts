/**
 * Rate limiter for Gemini Flash free tier (15 RPM / 1,500 RPD).
 * Tracks calls in memory (RPM) and localStorage (RPD).
 * Exports withRetry() for exponential backoff on 429 errors.
 */

const RPM_LIMIT = 15
const RPD_LIMIT = 1500
const MAX_RETRIES = 5
const BASE_BACKOFF_MS = 2000
const MAX_BACKOFF_MS = 60000

export class RateLimiter {
  private callTimestamps: number[] = []
  private dailyCalls = 0

  constructor() {
    this.loadDaily()
  }

  private loadDaily(): void {
    try {
      const storedDate = localStorage.getItem('gemini_daily_date')
      const today = new Date().toDateString()
      if (storedDate === today) {
        this.dailyCalls = parseInt(localStorage.getItem('gemini_daily_calls') ?? '0', 10)
      } else {
        this.dailyCalls = 0
      }
    } catch {
      this.dailyCalls = 0
    }
  }

  private persistDaily(): void {
    try {
      localStorage.setItem('gemini_daily_calls', String(this.dailyCalls))
      localStorage.setItem('gemini_daily_date', new Date().toDateString())
    } catch {
      // localStorage unavailable (e.g. incognito with storage disabled)
    }
  }

  get remainingDaily(): number {
    this.loadDaily()
    return Math.max(0, RPD_LIMIT - this.dailyCalls)
  }

  /**
   * Wait until a rate-limit slot is available, then consume it.
   * Throws if daily limit is exhausted.
   */
  async acquire(): Promise<void> {
    this.loadDaily()
    if (this.dailyCalls >= RPD_LIMIT) {
      throw new Error(`Daily rate limit reached (${RPD_LIMIT} calls). Try again tomorrow.`)
    }

    // Prune timestamps older than 60 s
    const now = Date.now()
    this.callTimestamps = this.callTimestamps.filter(t => now - t < 60_000)

    if (this.callTimestamps.length >= RPM_LIMIT) {
      const waitMs = 60_000 - (now - this.callTimestamps[0]) + 100
      console.log(`[AGENT] RPM limit hit, waiting ${(waitMs / 1000).toFixed(1)}s`)
      await new Promise(r => setTimeout(r, waitMs))
    }

    this.callTimestamps.push(Date.now())
    this.dailyCalls++
    this.persistDaily()
  }
}

/* ------------------------------------------------------------------ */

function is429(err: unknown): boolean {
  if (err instanceof Error) {
    const m = err.message.toLowerCase()
    return (
      m.includes('429') ||
      m.includes('rate limit') ||
      m.includes('resource_exhausted') ||
      m.includes('quota')
    )
  }
  return false
}

/**
 * Wrap an async function with exponential back-off on 429 errors.
 */
export async function withRetry<T>(fn: () => Promise<T>): Promise<T> {
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      return await fn()
    } catch (err) {
      if (is429(err) && attempt < MAX_RETRIES) {
        const base = BASE_BACKOFF_MS * Math.pow(2, attempt)
        const jitter = Math.random() * 1000
        const wait = Math.min(base + jitter, MAX_BACKOFF_MS)
        console.log(
          `[AGENT] 429 → retry ${attempt + 1}/${MAX_RETRIES} in ${(wait / 1000).toFixed(1)}s`,
        )
        await new Promise(r => setTimeout(r, wait))
        continue
      }
      throw err
    }
  }
  throw new Error('Rate-limit retries exhausted')
}
