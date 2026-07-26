import { useCallback, useEffect, useState } from 'react'
import { api } from './api/client'
import type { EnumCatalog, Health, Providers, Task } from './api/types'
import { ImportView } from './import/ImportView'

const TABS = ['Import', 'Tasks', 'Calendar', 'Watch'] as const
type Tab = (typeof TABS)[number]

export default function App() {
  const [tab, setTab] = useState<Tab>('Import')
  const [health, setHealth] = useState<Health | null>(null)
  const [providers, setProviders] = useState<Providers | null>(null)
  const [enums, setEnums] = useState<EnumCatalog | null>(null)
  // Bumped after a commit so the task list refetches.
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    api.providers().then(setProviders).catch(() => setProviders(null))
    api.enums().then(setEnums).catch(() => setEnums(null))
  }, [])

  const onCommitted = useCallback(() => setRevision((r) => r + 1), [])

  return (
    <div className="app">
      <header className="masthead">
        <h1>{health?.app ?? 'Task Hub'}</h1>
        <span className="env">
          {health
            ? `${health.environment} · ${health.db_dialect}`
            : 'backend unreachable — is uvicorn running on :8000?'}
        </span>
      </header>

      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            aria-current={t === tab ? 'page' : undefined}
          >
            {t}
          </button>
        ))}
      </nav>

      {tab === 'Import' && (
        <ImportView providers={providers} enums={enums} onCommitted={onCommitted} />
      )}
      {tab === 'Tasks' && <TasksView revision={revision} />}
      {(tab === 'Calendar' || tab === 'Watch') && (
        <div className="panel empty">
          {tab} lands in phase {tab === 'Calendar' ? 2 : 3}.
        </div>
      )}
    </div>
  )
}

function TasksView({ revision }: { revision: number }) {
  const [tasks, setTasks] = useState<Task[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setTasks(null)
    api
      .listTasks()
      .then(setTasks)
      .catch((e) => setError(String(e)))
  }, [revision])

  if (error) return <div className="panel error">{error}</div>
  if (!tasks) return <div className="panel empty">Loading…</div>
  if (tasks.length === 0)
    return (
      <div className="panel empty">
        No committed tasks yet. Import some from the Import tab.
      </div>
    )

  return (
    <div className="panel">
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
            <tr key={t.id}>
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
  )
}
