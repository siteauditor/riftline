import { useEffect, useState, type ReactNode } from 'react'

/**
 * Copies a link, and says so. Where the clipboard is refused (an embedded
 * frame, an old browser, a page not served over HTTPS) the link is shown in a
 * field to copy by hand instead of failing silently.
 */
export default function CopyButton({
  text,
  className,
  children,
}: {
  text: string
  className: string
  children: ReactNode
}) {
  const [state, setState] = useState<'idle' | 'copied' | 'manual'>('idle')

  useEffect(() => {
    if (state !== 'copied') return
    const timer = window.setTimeout(() => setState('idle'), 2000)
    return () => window.clearTimeout(timer)
  }, [state])

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
    } catch {
      setState('manual')
    }
  }

  return (
    <>
      <button type="button" onClick={() => void copy()} className={className}>
        {state === 'copied' ? 'Copied' : children}
      </button>
      {state === 'manual' && (
        <input
          readOnly
          value={text}
          aria-label="Link to copy"
          onFocus={(e) => e.target.select()}
          autoFocus
          className="control min-w-0 flex-1 text-xs"
        />
      )}
    </>
  )
}
