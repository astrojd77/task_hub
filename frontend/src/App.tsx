import { useEffect, useState } from 'react'
import { api } from './api/client'
import type { Health, Providers, Task } from './api/types'

/**
 * Phase 0 shell. The tab set is the eventual product surface — Import (1),
 * Tasks (1), Calendar (2), Watch (3) — with only Tasks live so far.
 */
const TABS = ['Import', 'Tasks', 'Calendar', 'Watch'] as const
type Tab = (typeof TABS)[number]

export default function App() {
  const [tab, setTab] = useState<Tab>('Tasks')
  const [health, setHealth] = useState<Health | null>(null)
  const [providers, setProviders] = useState<Providers | null>(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    api.providers().then(setProviders).catch(() => setProviders(null))
  }, [])

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

      {tab === 'Tasks' ? (
        <TasksView />
      ) : (
        <Placeholder tab={tab} providers={providers} />
      )}
    </div>
  )
}

function TasksView() {
  const [tasks, setTasks] = useState<Task[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listTasks()
      .then(setTasks)
      .catch((e) => setError(String(e)))
  }, [])

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

function Placeholder({
  tab,
  providers,
}: {
  tab: Tab
  providers: Providers | null
}) {
  const phase = { Import: 1, Calendar: 2, Watch: 3 }[
    tab as 'Import' | 'Calendar' | 'Watch'
  ]
  return (
    <div className="panel">
      <p className="empty">{tab} lands in phase {phase}.</p>
      {providers && (
        <p className="env">
          Registered sources: {providers.sources.map((s) => s.id).join(', ') || 'none yet'}
          {' · '}
          destinations: {providers.destinations.map((d) => d.id).join(', ')}
        </p>
      )}
    </div>
  )
}
