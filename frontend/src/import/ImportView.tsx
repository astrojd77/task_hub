import { useState } from 'react'
import type { EnumCatalog, Providers } from '../api/types'
import { CsvImport } from './CsvImport'
import { EmailImport } from './EmailImport'
import { JiraImport } from './JiraImport'

/**
 * Source picker. The list comes from /api/providers, so an adapter registered
 * on the backend appears here without touching this file — only its panel
 * needs adding below.
 */
export function ImportView({
  providers,
  enums,
  onCommitted,
}: {
  providers: Providers | null
  enums: EnumCatalog | null
  onCommitted: () => void
}) {
  const sources = providers?.sources ?? []
  const [active, setActive] = useState<string | null>(null)
  const current = active ?? sources[0]?.id ?? null

  if (!enums) return <div className="panel empty">Loading…</div>
  if (sources.length === 0)
    return <div className="panel empty">No sources are enabled. Check ENABLED_SOURCES.</div>

  return (
    <div className="stack">
      <div className="source-picker">
        {sources.map((s) => (
          <button
            key={s.id}
            className={s.id === current ? 'chip active' : 'chip'}
            onClick={() => setActive(s.id)}
          >
            {s.display_name}
          </button>
        ))}
      </div>

      {current === 'csv' && <CsvImport enums={enums} onCommitted={onCommitted} />}
      {current === 'jira' && (
        <JiraImport
          info={sources.find((s) => s.id === 'jira')}
          enums={enums}
          onCommitted={onCommitted}
        />
      )}
      {current === 'email' && <EmailImport enums={enums} onCommitted={onCommitted} />}
      {current && !['csv', 'jira', 'email'].includes(current) && (
        <div className="panel empty">
          {sources.find((s) => s.id === current)?.display_name} has no import panel yet.
        </div>
      )}
    </div>
  )
}
