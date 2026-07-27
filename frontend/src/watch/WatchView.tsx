import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { EnumCatalog, WatchOut } from '../api/types'
import { FilterBar } from '../filters/FilterBar'
import { toQuery, useFacets, useFilters } from '../filters/filters'
import { TaskDetail } from '../tasks/TaskDetail'
import type { Task } from '../api/types'

/**
 * Read-only heads-up over committed tasks. No delivered alerts in v1 — this is
 * an in-app view.
 *
 * Every row shows its score *and* the reasons behind it, because a ranking you
 * cannot explain is one you cannot trust or tune.
 */
export function WatchView({ enums, revision }: { enums: EnumCatalog; revision: number }) {
  const { filters, set, toggle, reset } = useFilters()
  const facets = useFacets(revision)
  const [data, setData] = useState<WatchOut | null>(null)
  const [selected, setSelected] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let stale = false
    api
      .watch(toQuery(filters))
      .then((d) => !stale && (setData(d), setError(null)))
      .catch((e) => !stale && setError(String(e)))
    return () => {
      stale = true
    }
  }, [filters, revision])

  if (error) return <div className="panel error">{error}</div>
  if (!data) return <div className="panel empty">Loading…</div>

  const total = data.sections.reduce((n, s) => n + s.items.length, 0)

  return (
    <div className="stack">
      <FilterBar
        filters={filters}
        facets={facets}
        enums={enums}
        onSet={set}
        onToggle={toggle}
        onReset={reset}
      />

      <div className="panel">
        <div className="toolbar">
          <strong>As of {data.today}</strong>
          <span className="env">
            Done work is excluded. A task can appear in more than one section.
          </span>
          <span className="spacer" />
          <WeightsNote weights={data.weights} />
        </div>
      </div>

      {total === 0 ? (
        <div className="panel empty">Nothing needs watching. Enjoy it.</div>
      ) : (
        data.sections.map((section) => (
          <div className="panel" key={section.key}>
            <div className="toolbar">
              <strong>
                {section.label} <span className="count">{section.items.length}</span>
              </strong>
              <span className="env">{section.description}</span>
            </div>

            {section.items.length === 0 ? (
              <p className="empty">Nothing here.</p>
            ) : (
              <ul className="watch-list">
                {section.items.map((item) => (
                  <li key={item.task.id} onClick={() => setSelected(item.task)}>
                    <span className="score" title="Watch score">
                      {item.score}
                    </span>
                    <span className="watch-main">
                      <span className="watch-summary">{item.task.summary}</span>
                      <span className="env">
                        {[
                          item.task.project,
                          item.task.assignee,
                          item.task.due_date ? `due ${item.task.due_date}` : null,
                        ]
                          .filter(Boolean)
                          .join(' · ') || 'no project, assignee or due date'}
                      </span>
                      <span className="reasons">
                        {item.reasons.length ? item.reasons.join('  ·  ') : 'no score drivers'}
                      </span>
                    </span>
                    <span className="pill">{item.task.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))
      )}

      {selected && <TaskDetail task={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

/** Surfaces the weight table so the ranking is inspectable from the UI. */
function WeightsNote({ weights }: { weights: WatchOut['weights'] }) {
  return (
    <details className="weights">
      <summary className="env">How the score works</summary>
      <div className="weights-body">
        <p className="env">
          Edit <code>WatchWeights</code> in <code>app/services/watch.py</code> and every
          section reorders.
        </p>
        <ul>
          <li>criticality: {fmt(weights.criticality)}</li>
          <li>impact: {fmt(weights.impact)}</li>
          <li>
            overdue +{weights.overdue} · due ≤2d +{weights.due_within_2_days} · due ≤
            {weights.due_soon_days}d +{weights.due_within_7_days}
          </li>
          <li>blocked +{weights.blocked}</li>
        </ul>
      </div>
    </details>
  )
}

function fmt(table: Record<string, number>): string {
  return Object.entries(table)
    .map(([k, v]) => `${k} +${v}`)
    .join(', ')
}
