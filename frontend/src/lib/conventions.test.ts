// @vitest-environment node
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

/**
 * Two of CLAUDE.md's rules, held for every component rather than for the pages
 * a browser test happens to open.
 *
 * No `title` attribute. It explains a figure to a mouse and to nobody else: not
 * a phone, not a keyboard, and a screen reader only sometimes. About 80 were
 * left across the site on 2026-09-24, one on every item icon because no test
 * drew an item. An explanation is a `Hint`, which opens on focus too, or words
 * on the page. An iframe's title is its accessible name, and may stay.
 *
 * No hand-written memo. The React Compiler memoises every component and hook,
 * and a `useMemo` or `useCallback` beside it is a second cache, which goes
 * stale the day its dependency list is wrong.
 */

// Every source file, as text. Tests and generated types are not shipped.
const sources = import.meta.glob<string>(
  ['../**/*.{ts,tsx}', '!../**/*.d.ts', '!../**/*.test.{ts,tsx}', '!../test/**'],
  { query: '?raw', import: 'default', eager: true },
)

const NAMED_BY_TITLE = new Set(['iframe'])
const MEMO = /^(React\.)?(useMemo|useCallback|memo)$/

function scan(path: string, text: string) {
  const kind = path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kind)
  const at = (node: ts.Node) =>
    `${path.replace(/^\.\.\//, 'src/')}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}`
  const titles: string[] = []
  const memos: string[] = []
  const visit = (node: ts.Node) => {
    if (ts.isJsxAttribute(node) && node.name.getText(source) === 'title') {
      // A lowercase tag is an element; `title` on a component is its own prop.
      const tag = (node.parent.parent as ts.JsxOpeningLikeElement).tagName.getText(source)
      if (/^[a-z]/.test(tag) && !NAMED_BY_TITLE.has(tag)) titles.push(`${at(node)} <${tag}>`)
    }
    if (ts.isCallExpression(node) && MEMO.test(node.expression.getText(source))) {
      memos.push(`${at(node)} ${node.expression.getText(source)}`)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return { titles, memos }
}

const found = Object.entries(sources).map(([path, text]) => scan(path, text))

describe('every component', () => {
  it('is read from the source tree', () => {
    // A glob that matched nothing would let everything below pass.
    expect(Object.keys(sources).length).toBeGreaterThan(100)
    expect(Object.keys(sources)).toContain('../components/Hint.tsx')
  })

  it('explains a figure with a Hint or words on the page, never a title attribute', () => {
    expect(found.flatMap((f) => f.titles)).toEqual([])
  })

  it('leaves memoising to the React Compiler', () => {
    expect(found.flatMap((f) => f.memos)).toEqual([])
  })
})
