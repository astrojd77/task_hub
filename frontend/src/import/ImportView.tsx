import { useState } from 'react'
import type { EnumCatalog, Providers } from '../api/types'
import { CsvImport } from './CsvImport'

/**
 * Source picker. The list comes from /api/providers, so registering a new
 * adapter on the backend makes it appear here with no change to this file —
 * only the per-source panel below needs adding.
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

      {current === 'csv' ? (
        <CsvImport enums={enums} onCommitted={onCommitted} />
      ) : (
        <div className="panel empty">
          {sources.find((s) => s.id === current)?.display_name} lands in{' '}
          {current === 'jira' ? 'phase 4' : 'phase 5'}.
        </div>
      )}
    </div>
  )
}
