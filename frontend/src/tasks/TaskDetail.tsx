import { useEffect } from 'react'
import type { Providers, Task } from '../api/types'
import { RoutingPanel } from './RoutingPanel'

/**
 * Detail popup, shared by the task list and the calendar.
 *
 * Read-only unless the caller supplies routing controls: the task list passes
 * them, the calendar opens the same popup without them.
 */
export function TaskDetail({
  task,
  providers,
  onChanged,
  onClose,
}: {
  task: Task
  providers?: Providers | null
  onChanged?: () => void
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={task.summary}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2>{task.summary}</h2>
          <button className="linkish" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {task.description && <p className="desc">{task.description}</p>}

        <dl className="detail-grid">
          <Row label="Status" value={task.status} />
          <Row label="Priority" value={task.priority} />
          <Row label="Criticality" value={task.criticality} />
          <Row label="Impact" value={task.impact_size} />
          <Row label="Due" value={task.due_date} />
          <Row label="Project" value={task.project} />
          <Row label="Assignee" value={task.assignee} />
          <Row label="Labels" value={task.labels.join(', ') || null} />
          <Row label="Source" value={`${task.source_provider} · ${task.source_ref}`} />
          <Row label="Destination" value={task.destination} />
          {Object.entries(task.external_refs).map(([provider, id]) => (
            <Row key={provider} label={`Pushed to ${provider}`} value={id} />
          ))}
        </dl>

        {onChanged && (
          <RoutingPanel task={task} providers={providers ?? null} onChanged={onChanged} />
        )}
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string | null }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value ?? '—'}</dd>
    </>
  )
}
