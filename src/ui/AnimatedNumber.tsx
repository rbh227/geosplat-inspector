import { useEffect, useRef, useState } from 'react'

interface AnimatedNumberProps {
  value: number
  duration?: number
  className?: string
}

function formatWithCommas(n: number): string {
  return Math.round(n).toLocaleString('en-US')
}

export default function AnimatedNumber({
  value,
  duration = 400,
  className = '',
}: AnimatedNumberProps) {
  const [display, setDisplay] = useState(value)
  const [pop, setPop] = useState(false)
  const prevRef = useRef(value)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    const from = prevRef.current
    const to = value
    prevRef.current = value

    if (from === to) return

    // Trigger pop animation
    setPop(true)
    const popTimer = setTimeout(() => setPop(false), 300)

    const start = performance.now()

    function tick(now: number) {
      const elapsed = now - start
      const progress = Math.min(elapsed / duration, 1)
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3)
      const current = from + (to - from) * eased

      setDisplay(current)

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        setDisplay(to)
      }
    }

    rafRef.current = requestAnimationFrame(tick)

    return () => {
      clearTimeout(popTimer)
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
      }
    }
  }, [value, duration])

  return (
    <span className={`${className} ${pop ? 'animate-badge-pop' : ''}`.trim()}>
      {formatWithCommas(display)}
    </span>
  )
}
