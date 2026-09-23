import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

/**
 * Copies a link, and says so. Where the clipboard is refused (an embedded
 * frame, an old browser, a page not served over HTTPS) the link is shown in a
 * field to copy by hand instead of failing silently.
 *
 * `text` may be a function, read at the click: the draft copies the page's own
 * address, and reading `window.location` during render would not survive the
 * prerender.
 */
export default function CopyButton({
  text,
  className,
  children,
}: {
  text: string | (() => string)
  className: string
  children: ReactNode
}) {
  const [state, setState] = useState<'idle' | 'copied' | 'manual'>('idle')
  const [copied, setCopied] = useState('')

  useEffect(() => {
    if (state !== 'copied') return
    const timer = window.setTimeout(() => setState('idle'), 2000)
    return () => window.clearTimeout(timer)
  }, [state])

  async function copy() {
    const value = typeof text === 'function' ? text() : text
    setCopied(value)
    try {
      await navigator.clipboard.writeText(value)
      setState('copied')
      toast('Link copied')
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
          value={copied}
          aria-label="Link to copy"
          onFocus={(e) => e.target.select()}
          autoFocus
          className="control min-w-0 flex-1 text-xs"
        />
      )}
    </>
  )
}
