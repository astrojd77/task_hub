import { useCallback, useRef, useState } from 'react'
import { api } from '../api/client'
import type { CommitResult, DraftBatch, DraftTask, EnumCatalog } from '../api/types'
import { useFieldConfig } from '../config/useFieldConfig'
import { ReviewTable, isCommittable } from '../review/ReviewTable'

/**
 * CSV import: choose a file, confirm the column mapping, review every row,
 * commit the ones you want.
 *
 * The file stays in browser memory so a mapping change simply re-posts it. The
 * server therefore keeps no per-upload state, and column mapping and value
 * normalisation stay in the adapter rather than being duplicated here.
 */
export function CsvImport({
  enums,
  configRevision = 0,
  onCommitted,
}: {
  enums: EnumCatalog
  configRevision?: number
  onCommitted: () => void
}) {
  const { customFields } = useFieldConfig(configRevision)
  const [file, setFile] = useState<File | null>(null)
  const [batch, setBatch] = useState<DraftBatch | null>(null)
  const [drafts, setDrafts] = useState<DraftTask[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<CommitResult | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(
    async (f: File, mapping?: Record<string, string>) => {
      setBusy(true)
      setError(null)
      setResult(null)
      try {
        const next = await api.buildDrafts('csv', f, mapping ? { mapping } : {})
        setBatch(next)
        setDrafts(next.drafts)
        // Pre-select everything that could be committed as-is; rows missing a
        // title stay unselected until the reviewer fixes them.
        setSelected(
          new Set(next.drafts.map((d, i) => (isCommittable(d) ? i : -1)).filter((i) => i >= 0)),
        )
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        setBatch(null)
        setDrafts([])
      } finally {
        setBusy(false)
      }
    },
    [],
  )

  function pick(f: File | null) {
    if (!f) return
    setFile(f)
    void load(f)
  }

  function remap(field: string, column: string) {
    if (!file || !batch) return
    const mapping = { ...(batch.meta.mapping ?? {}) }
    if (column) mapping[field] = column
    else delete mapping[field]
    void load(file, mapping)
  }

  function edit(index: number, patch: Partial<DraftTask>) {
    setDrafts((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], ...patch }
      // A row that just became valid should not silently stay unselected.
      if (patch.title !== undefined && isCommittable(next[index])) {
        setSelected((s) => new Set(s).add(index))
      }
      return next
    })
  }

  async function commit() {
    setBusy(true)
    setError(null)
    try {
      const chosen = drafts.filter((_, i) => selected.has(i))
      setResult(await api.commit(chosen))
      onCommitted()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const committable = drafts.filter((d, i) => selected.has(i) && isCommittable(d)).length

  return (
    <div className="stack">
      <div
        className={`dropzone${dragging ? ' dragging' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          pick(e.dataTransfer.files?.[0] ?? null)
        }}
      >
        <p>
          <strong>Drop a CSV here</strong> or{' '}
          <button className="linkish" onClick={() => inputRef.current?.click()}>
            choose a file
          </button>
        </p>
        {file && (
          <p className="env">
            {file.name}
            {batch?.meta.row_count !== undefined && ` · ${batch.meta.row_count} rows`}
          </p>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.tsv,text/csv"
          hidden
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
        />
      </div>

      {error && <div className="panel error">{error}</div>}
      {busy && <p className="env">Working…</p>}

      {batch && batch.meta.columns && (
        <MappingEditor meta={batch.meta} onChange={remap} />
      )}

      {batch && drafts.length > 0 && (
        <div className="panel">
          <div className="toolbar">
            <strong>Review {drafts.length} rows</strong>
            <span className="env">
              Fill in criticality and impact here — the CSV rarely carries them.
            </span>
            <span className="spacer" />
            <span className="env">{committable} selected</span>
            <button
              className="primary"
              disabled={busy || committable === 0}
              onClick={() => void commit()}
            >
              Commit {committable} task{committable === 1 ? '' : 's'}
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
      )}

      {result && <CommitSummary result={result} />}
    </div>
  )
}

function MappingEditor({
  meta,
  onChange,
}: {
  meta: DraftBatch['meta']
  onChange: (field: string, column: string) => void
}) {
  const fields = meta.mappable_fields ?? []
  const columns = meta.columns ?? []
  const mapping = meta.mapping ?? {}

  return (
    <div className="panel">
      <div className="toolbar">
        <strong>Column mapping</strong>
        <span className="env">Auto-detected from the headers — change any that are wrong.</span>
      </div>
      <div className="mapping-grid">
        {fields.map((field) => (
          <label key={field}>
            <span>{field}</span>
            <select value={mapping[field] ?? ''} onChange={(e) => onChange(field, e.target.value)}>
              <option value="">— not mapped —</option>
              {columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
    </div>
  )
}

function CommitSummary({ result }: { result: CommitResult }) {
  return (
    <div className="panel">
      <p>
        <strong className="ok">
          Committed — {result.created} created, {result.updated} updated.
        </strong>
      </p>
      {result.errors.length > 0 && (
        <ul className="row-notes">
          {result.errors.map((e, i) => (
            <li key={i} className="error">
              row {e.index + 1}: {e.message}
            </li>
          ))}
        </ul>
      )}
      {result.warnings.length > 0 && (
        <details>
          <summary className="env">{result.warnings.length} warnings</summary>
          <ul className="row-notes">
            {result.warnings.map((w, i) => (
              <li key={i} className="warn">
                row {w.index + 1}: {w.message}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
