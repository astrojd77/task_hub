import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DestinationResolution, Providers, Task } from '../api/types'

/**
 * Per-task routing, inside the detail popup.
 *
 * Shows where the task *would* go and which rule decided that, because
 * "resolved: jira" is much less useful than "jira, because it is the default
 * for project Platform".
 */
export function RoutingPanel({
  task,
  providers,
  onChanged,
}: {
  task: Task
  providers: Providers | null
  onChanged: () => void
}) {
  const [resolution, setResolution] = useState<DestinationResolution | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pushed, setPushed] = useState<string | null>(null)

  useEffect(() => {
    api
      .taskDestination(task.id)
      .then(setResolution)
      .catch(() => setResolution(null))
  }, [task.id])

  const destinations = providers?.destinations ?? []

  async function choose(value: string) {
    setBusy(true)
    setError(null)
    try {
      await api.setTaskDestination(task.id, value || null)
      setResolution(await api.taskDestination(task.id))
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function push() {
    setBusy(true)
    setError(null)
    setPushed(null)
    try {
      const result = await api.pushTask(task.id)
      setPushed(
        `${result.action} ${result.external_id} on ${result.destination}` +
          (result.url ? ` — ${result.url}` : ''),
      )
      setResolution(await api.taskDestination(task.id))
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="routing">
      <div className="toolbar">
        <label className="facet">
          <span>Destination</span>
          <select
            value={resolution?.explicit ?? ''}
            disabled={busy}
            onChange={(e) => void choose(e.target.value)}
          >
            <option value="">
              Use project default{resolution ? ` (${resolution.resolved})` : ''}
            </option>
            {destinations.map((d) => (
              <option key={d.id} value={d.id}>
                {d.display_name}
              </option>
            ))}
          </select>
        </label>

        <span className="spacer" />
        <button className="primary" disabled={busy} onClick={() => void push()}>
          {busy ? 'Working…' : `Push to ${resolution?.resolved ?? 'destination'}`}
        </button>
      </div>

      {resolution && (
        <p className="env">
          Resolves to <strong>{resolution.resolved}</strong> — {resolution.reason}.
        </p>
      )}
      {pushed && <p className="ok">{pushed}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

/** Project-level defaults, shown above the task list. */
export function ProjectRoutes({
  providers,
  projects,
  revision,
}: {
  providers: Providers | null
  projects: string[]
  revision: number
}) {
  const [routes, setRoutes] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    api
      .routes()
      .then((rs) => setRoutes(Object.fromEntries(rs.map((r) => [r.project, r.destination]))))
      .catch(() => setRoutes({}))
  }, [revision])

  async function set(project: string, destination: string) {
    try {
      await api.setRoute(project, destination || null)
      setRoutes((r) => {
        const next = { ...r }
        if (destination) next[project] = destination
        else delete next[project]
        return next
      })
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  if (projects.length === 0) return null

  return (
    <div className="panel">
      <div className="toolbar">
        <button className="linkish" onClick={() => setOpen((o) => !o)}>
          {open ? 'Hide' : 'Show'} project destination defaults
        </button>
        <span className="env">
          A task's own destination always wins; this is the fallback per project.
        </span>
      </div>

      {open && (
        <div className="mapping-grid">
          {projects.map((project) => (
            <label key={project}>
              <span>{project}</span>
              <select value={routes[project] ?? ''} onChange={(e) => void set(project, e.target.value)}>
                <option value="">local (default)</option>
                {(providers?.destinations ?? []).map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.display_name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}

      {error && <p className="error">{error}</p>}
    </div>
  )
}
