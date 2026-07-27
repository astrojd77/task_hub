import { useCallback, useEffect, useState } from 'react'
import { api } from './api/client'
import type { EnumCatalog, Health, Providers } from './api/types'
import { CalendarView } from './calendar/CalendarView'
import { ConfigView } from './config/ConfigView'
import { ImportView } from './import/ImportView'
import { TasksView } from './tasks/TasksView'
import { WatchView } from './watch/WatchView'

const TABS = ['Import', 'Tasks', 'Calendar', 'Watch', 'Config'] as const
type Tab = (typeof TABS)[number]

export default function App() {
  const [tab, setTab] = useState<Tab>('Import')
  const [health, setHealth] = useState<Health | null>(null)
  const [providers, setProviders] = useState<Providers | null>(null)
  const [enums, setEnums] = useState<EnumCatalog | null>(null)
  // Bumped after a commit or a push so every view refetches.
  const [revision, setRevision] = useState(0)
  // Separate counter: saving a field definition must refresh the review
  // dropdowns and the enum catalog, but need not refetch the task lists.
  const [configRevision, setConfigRevision] = useState(0)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    api.providers().then(setProviders).catch(() => setProviders(null))
    api.enums().then(setEnums).catch(() => setEnums(null))
  }, [])

  const refresh = useCallback(() => setRevision((r) => r + 1), [])
  const refreshConfig = useCallback(() => {
    setConfigRevision((r) => r + 1)
    // Builtin scales feed /api/enums, so re-pull it when they change.
    api.enums().then(setEnums).catch(() => undefined)
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
          <button key={t} onClick={() => setTab(t)} aria-current={t === tab ? 'page' : undefined}>
            {t}
          </button>
        ))}
      </nav>

      {!enums ? (
        <div className="panel empty">Loading…</div>
      ) : (
        <>
          {tab === 'Import' && (
            <ImportView
              providers={providers}
              enums={enums}
              configRevision={configRevision}
              onCommitted={refresh}
            />
          )}
          {tab === 'Tasks' && (
            <TasksView
              enums={enums}
              providers={providers}
              revision={revision}
              onChanged={refresh}
            />
          )}
          {tab === 'Calendar' && <CalendarView enums={enums} revision={revision} />}
          {tab === 'Watch' && <WatchView enums={enums} revision={revision} />}
          {tab === 'Config' && <ConfigView onChanged={refreshConfig} />}
        </>
      )}
    </div>
  )
}
