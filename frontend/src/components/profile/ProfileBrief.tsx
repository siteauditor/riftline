/**
 * The page in sentences, from its own numbers: for a reader who does not know
 * the game, and for anything that reads the page without a browser.
 *
 * Below the games and the rail, across the page. It used to open the column,
 * and at four sentences it was one of the things between a phone's first
 * screen and the first game.
 */
export default function ProfileBrief({ riotId, sentences }: { riotId: string; sentences: string[] }) {
  if (sentences.length === 0) return null
  return (
    <section
      aria-label={`${riotId} in brief`}
      className="mt-8 max-w-prose space-y-1.5 border-t border-line-soft pt-5 text-sm leading-relaxed text-ink-dim"
    >
      <h2 className="eyebrow mb-2">In brief</h2>
      {sentences.map((sentence, i) => (
        <p key={i} className={i === 0 ? 'text-ink' : undefined}>
          {sentence}
        </p>
      ))}
    </section>
  )
}
