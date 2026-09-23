// Generate src/lib/api.gen.d.ts from openapi.json, the API's own document.
//
//     node scripts/api-types.mjs [--in openapi.json] [--out src/lib/api.gen.d.ts]
//
// openapi.json is written by the backend (`python -m scripts.openapi`), and
// CI regenerates both files and fails on a difference, so the types the
// pages compile against are the API's, not a copy kept in step by hand.
//
// One adjustment before generating. Pydantic marks a field with a default
// as optional in the schema, and a field whose default is a factory (every
// list and dict) carries no default at all, so a response type generated
// as-is would say `roles?: RoleShare[]` about a field the API always sends.
// FastAPI serialises every field of a response model, so every property of
// a response schema is made required here. Request bodies are left as they
// are: there the optional fields really are optional.

import { readFileSync, writeFileSync } from 'node:fs'

import openapiTS, { astToString } from 'openapi-typescript'

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, arg, i, all) => {
    if (arg.startsWith('--')) pairs.push([arg.slice(2), all[i + 1]])
    return pairs
  }, []),
)
const input = args.in ?? 'openapi.json'
const output = args.out ?? 'src/lib/api.gen.d.ts'

const schema = JSON.parse(readFileSync(input, 'utf8'))
const isRequestBody = (name) => name.endsWith('Request') || name === 'HTTPValidationError' || name === 'ValidationError'
for (const [name, def] of Object.entries(schema.components?.schemas ?? {})) {
  if (isRequestBody(name) || !def.properties) continue
  def.required = Object.keys(def.properties)
}

// Explicit: the generator's default treats a field with a default value as
// required, which is wrong for a request body the page may send without it.
const ast = await openapiTS(schema, { defaultNonNullable: false })
const banner =
  '// Generated from openapi.json by scripts/api-types.mjs (`pnpm api:types`). Do not edit.\n\n'
writeFileSync(output, banner + astToString(ast))
console.log(`wrote ${output} from ${input}`)
