import { useState } from 'react'
import { api } from '../api/client'
import type { CommitResult, DraftBatch, EnumCatalog, SourceInfo } from '../api/types'
import { CommitSummary, DraftReview } from './DraftReview'

/**
 * Jira import — targeted only.
 *
 * One issue key or one JQL query, never a blanket pull. Credentials live in
 * server config and are never sent from here; only the targeting is.
 */
export function JiraImport({
  info,
  enums,
  configRevision = 0,
  onCommitted,
}: {
  info: SourceInfo | undefined
  enums: EnumCatalog
  configRevision?: number
  onCommitted: () => void
}) {
  const [mode, setMode] = useState<'key' | 'jql'>('key')
  const [issueKey, setIssueKey] = useState('')
  const [jql, setJql] = useState('')
  const [batch, setBatch] = useState<DraftBatch | null>(null)
  const [result, setResult] = useState<CommitResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const configured = info?.config_schema?.configured !== false
  const target = mode === 'key' ? issueKey.trim() : jql.trim()

  async function fetchDrafts() {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const config = mode === 'key' ? { issue_key: issueKey.trim() } : { jql: jql.trim() }
      setBatch(await api.buildDrafts('jira', null, config))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBatch(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      {!configured && (
        <div className="panel warn-panel">
          Jira is not configured. Set <code>JIRA_BASE_URL</code>, <code>JIRA_EMAIL</code> and{' '}
          <code>JIRA_API_TOKEN</code> in the server environment.
        </div>
      )}

      <div className="panel">
        <div className="toolbar">
          <button
            className={mode === 'key' ? 'chip active' : 'chip'}
            onClick={() => setMode('key')}
          >
            One issue
          </button>
          <button
            className={mode === 'jql' ? 'chip active' : 'chip'}
            onClick={() => setMode('jql')}
          >
            JQL query
          </button>
          <span className="env">Targeted fetches only — there is no "import everything".</span>
        </div>

        {mode === 'key' ? (
          <label className="stacked-field">
            <span>Issue key</span>
            <input
              value={issueKey}
              placeholder="OPS-123"
              onChange={(e) => setIssueKey(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && target && void fetchDrafts()}
            />
          </label>
        ) : (
          <label className="stacked-field">
            <span>JQL</span>
            <textarea
              rows={3}
              value={jql}
              placeholder="project = OPS AND status != Done ORDER BY duedate"
              onChange={(e) => setJql(e.target.value)}
            />
          </label>
        )}

        <div className="toolbar">
          {(info?.config_schema?.criticality_field || info?.config_schema?.impact_field) && (
            <span className="env">
              Reading criticality/impact from{' '}
              {[info.config_schema.criticality_field, info.config_schema.impact_field]
                .filter(Boolean)
                .join(' and ')}
            </span>
          )}
          <span className="spacer" />
          <button className="primary" disabled={busy || !target} onClick={() => void fetchDrafts()}>
            {busy ? 'Fetching…' : 'Fetch for review'}
          </button>
        </div>
      </div>

      {error && <div className="panel error">{error}</div>}

      {batch && (
        <DraftReview
          batch={batch}
          enums={enums}
          configRevision={configRevision}
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
