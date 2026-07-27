import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { CommitResult, DraftBatch, DraftTask, EnumCatalog } from '../api/types'
import { useFieldConfig } from '../config/useFieldConfig'
import { ReviewModal } from '../review/ReviewModal'
import { ReviewTable, isCommittable } from '../review/ReviewTable'

/**
 * Review-and-commit for any source's batch.
 *
 * Single item gets the modal, many get the table — the *adapter* decides via
 * `meta.review_style`, because it is the thing that knows whether it fetched
 * one issue or ran a query. Falls back to the draft count when a source has no
 * opinion.
 */
export function DraftReview({
  batch,
  enums,
  configRevision = 0,
  onCommitted,
  onDismiss,
}: {
  batch: DraftBatch
  enums: EnumCatalog
  configRevision?: number
  onCommitted: (result: CommitResult) => void
  onDismiss: () => void
}) {
  const [drafts, setDrafts] = useState<DraftTask[]>(batch.drafts)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { customFields } = useFieldConfig(configRevision)

  useEffect(() => {
    setDrafts(batch.drafts)
    setSelected(
      new Set(batch.drafts.map((d, i) => (isCommittable(d) ? i : -1)).filter((i) => i >= 0)),
    )
    setError(null)
  }, [batch])

  const asModal = batch.meta.review_style === 'modal' || drafts.length === 1

  function edit(index: number, patch: Partial<DraftTask>) {
    setDrafts((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], ...patch }
      if (patch.summary !== undefined && isCommittable(next[index])) {
        setSelected((s) => new Set(s).add(index))
      }
      return next
    })
  }

  async function commit(chosen: DraftTask[]) {
    setBusy(true)
    setError(null)
    try {
      onCommitted(await api.commit(chosen))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (drafts.length === 0) {
    return <div className="panel empty">Nothing came back to review.</div>
  }

  if (asModal) {
    return (
      <>
        {error && <div className="panel error">{error}</div>}
        <ReviewModal
          draft={drafts[0]}
          enums={enums}
          customFields={customFields}
          busy={busy}
          onChange={(patch) => edit(0, patch)}
          onCommit={() => void commit([drafts[0]])}
          onClose={onDismiss}
        />
      </>
    )
  }

  const count = drafts.filter((d, i) => selected.has(i) && isCommittable(d)).length

  return (
    <div className="panel">
      {error && <div className="error">{error}</div>}
      <div className="toolbar">
        <strong>Review {drafts.length} items</strong>
        <span className="env">
          Fill in criticality and impact here — most sources cannot supply them.
        </span>
        <span className="spacer" />
        <span className="env">{count} selected</span>
        <button
          className="primary"
          disabled={busy || count === 0}
          onClick={() => void commit(drafts.filter((_, i) => selected.has(i)))}
        >
          Commit {count} task{count === 1 ? '' : 's'}
        </button>
      </div>

      <ReviewTable
        drafts={drafts}
        enums={enums}
        customFields={customFields}
        selected={selected}
        onToggle={(i) =>
          setSelected((s) => {
            const next = new Set(s)
            if (next.has(i)) next.delete(i)
            else next.add(i)
            return next
          })
        }
        onToggleAll={(checked) =>
          setSelected(
            checked
              ? new Set(drafts.map((d, i) => (isCommittable(d) ? i : -1)).filter((i) => i >= 0))
              : new Set(),
          )
        }
        onChange={edit}
      />
    </div>
  )
}

export function CommitSummary({ result }: { result: CommitResult }) {
  return (
    <div className="panel">
      <p>
        <strong className="ok">
          Committed — {result.created} created, {result.updated} updated.
        </strong>
      </p>
      {result.errors.length > 0 && (
        <ul className="row-notes stacked">
          {result.errors.map((e, i) => (
            <li key={i} className="error">
              item {e.index + 1}: {e.message}
            </li>
          ))}
        </ul>
      )}
      {result.warnings.length > 0 && (
        <details>
          <summary className="env">{result.warnings.length} warnings</summary>
          <ul className="row-notes stacked">
            {result.warnings.map((w, i) => (
              <li key={i} className="warn">
                item {w.index + 1}: {w.message}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
