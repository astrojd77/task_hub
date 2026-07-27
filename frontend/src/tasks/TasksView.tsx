import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { EnumCatalog, Task } from '../api/types'
import { FilterBar } from '../filters/FilterBar'
import { toQuery, useFacets, useFilters } from '../filters/filters'
import { TaskDetail } from './TaskDetail'

export function TasksView({ enums, revision }: { enums: EnumCatalog; revision: number }) {
  const { filters, set, toggle, reset } = useFilters()
  const facets = useFacets(revision)
  const [tasks, setTasks] = useState<Task[] | null>(null)
  const [selected, setSelected] = useState<Task | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let stale = false
    api
      .listTasks(toQuery(filters))
      .then((t) => {
        if (!stale) {
          setTasks(t)
          setError(null)
        }
      })
      .catch((e) => !stale && setError(String(e)))
    // Guards against an older, slower response overwriting a newer one when
    // filters change quickly.
    return () => {
      stale = true
    }
  }, [filters, revision])

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

      {error && <div className="panel error">{error}</div>}

      {!tasks ? (
        <div className="panel empty">Loading…</div>
      ) : tasks.length === 0 ? (
        <div className="panel empty">No tasks match these filters.</div>
      ) : (
        <div className="panel">
          <div className="review-scroll">
            <table className="tasks">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Priority</th>
                  <th>Criticality</th>
                  <th>Impact</th>
                  <th>Due</th>
                  <th>Project</th>
                  <th>Assignee</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.id} className="clickable" onClick={() => setSelected(t)}>
                    <td>{t.title}</td>
                    <td>
                      <span className="pill">{t.status}</span>
                    </td>
                    <td>{t.priority}</td>
                    <td>{t.criticality ?? '—'}</td>
                    <td>{t.impact_size ?? '—'}</td>
                    <td>{t.due_date ?? '—'}</td>
                    <td>{t.project ?? '—'}</td>
                    <td>{t.assignee ?? '—'}</td>
                    <td>
                      <span className="pill">{t.source_provider}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {selected && <TaskDetail task={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
