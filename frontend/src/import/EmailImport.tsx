import { useRef, useState } from 'react'
import { api } from '../api/client'
import type { CommitResult, DraftBatch, EnumCatalog } from '../api/types'
import { CommitSummary, DraftReview } from './DraftReview'

/**
 * Email import — drop a saved .msg or .eml, or pick one.
 *
 * The picker is not a nicety: dragging straight out of the Outlook desktop app
 * exposes a virtual file the browser usually cannot read, so "save it first,
 * then pick it" is the reliable path. Dragging a *saved* file works fine.
 */
export function EmailImport({
  enums,
  onCommitted,
}: {
  enums: EnumCatalog
  onCommitted: () => void
}) {
  const [batch, setBatch] = useState<DraftBatch | null>(null)
  const [result, setResult] = useState<CommitResult | null>(null)
  const [filename, setFilename] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function load(file: File | null) {
    if (!file) return
    setFilename(file.name)
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setBatch(await api.buildDrafts('email', file))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBatch(null)
    } finally {
      setBusy(false)
    }
  }

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
          void load(e.dataTransfer.files?.[0] ?? null)
        }}
      >
        <p>
          <strong>Drop a saved .msg or .eml here</strong> or{' '}
          <button className="linkish" onClick={() => inputRef.current?.click()}>
            choose a file
          </button>
        </p>
        <p className="env">
          Parsed locally — no Outlook or Graph connection. Dragging directly out of the Outlook
          desktop app is unreliable; save the message first, then drop or pick it.
        </p>
        {filename && <p className="env">{filename}</p>}
        <input
          ref={inputRef}
          type="file"
          accept=".msg,.eml,message/rfc822,application/vnd.ms-outlook"
          hidden
          onChange={(e) => void load(e.target.files?.[0] ?? null)}
        />
      </div>

      {busy && <p className="env">Parsing…</p>}
      {error && <div className="panel error">{error}</div>}

      {batch && (
        <DraftReview
          batch={batch}
          enums={enums}
          onDismiss={() => setBatch(null)}
          onCommitted={(r) => {
            setResult(r)
            setBatch(null)
            onCommitted()
          }}
        />
      )}

      {result && <CommitSummary result={result} />}
    </div>
  )
}
