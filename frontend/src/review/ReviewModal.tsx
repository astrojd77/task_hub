import { useState } from 'react'
import type { DraftTask, EnumCatalog, FieldConfig } from '../api/types'
import { validateDraft } from './ReviewTable'
import { UnmappedRule } from './UnmappedRule'

/**
 * Single-item review. Used when a source produces exactly one draft — an
 * email, or a Jira fetch by issue key. A JQL query with many results gets the
 * review *table* instead; the adapter says which via DraftBatch.meta.
 *
 * Same rules as the table, laid out as a form because there is room for one.
 */
export function ReviewModal({
  draft,
  enums,
  customFields = [],
  allFields = [],
  busy,
  onChange,
  onCommit,
  onClose,
}: {
  draft: DraftTask
  enums: EnumCatalog
  /** User-configured dropdowns from the Config screen. */
  customFields?: FieldConfig[]
  /** Every configured field, so unmapped values can offer their options. */
  allFields?: FieldConfig[]
  busy: boolean
  onChange: (patch: Partial<DraftTask>) => void
  onCommit: () => void
  onClose: () => void
}) {
  const [showRaw, setShowRaw] = useState(false)
  const issues = validateDraft(draft)
  const blocked = issues.some((i) => i.blocking)

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal wide"
        role="dialog"
        aria-modal="true"
        aria-label="Review before committing"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2>Review before committing</h2>
          <button className="linkish" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {draft.unmapped?.length > 0 && (
          <div className="unmapped-block">
            {draft.unmapped.map((u, k) => (
              <UnmappedRule
                key={`${u.field_key}-${k}`}
                draft={draft}
                unmapped={u}
                fields={allFields}
                onApply={onChange}
              />
            ))}
          </div>
        )}

        {(draft.warnings.length > 0 || issues.length > 0) && (
          <ul className="row-notes stacked">
            {draft.warnings.map((w, i) => (
              <li key={`w${i}`} className="warn">
                {w}
              </li>
            ))}
            {issues.map((i, k) => (
              <li key={`i${k}`} className={i.blocking ? 'error' : 'warn'}>
                {i.message}
              </li>
            ))}
          </ul>
        )}

        <div className="form-grid">
          <label className="span2">
            <span>Title *</span>
            <input
              className={blocked ? 'invalid' : undefined}
              value={draft.summary}
              placeholder="Required"
              onChange={(e) => onChange({ summary: e.target.value })}
            />
          </label>

          <label className="span2">
            <span>Description</span>
            <textarea
              rows={5}
              value={draft.description ?? ''}
              onChange={(e) => onChange({ description: e.target.value || null })}
            />
          </label>

          <Select
            label="Status"
            options={enums.status}
            value={draft.status}
            onChange={(v) => onChange({ status: v as DraftTask['status'] })}
          />
          <Select
            label="Priority"
            options={enums.priority}
            value={draft.priority}
            onChange={(v) => onChange({ priority: v as DraftTask['priority'] })}
          />
          <Select
            label="Criticality"
            options={enums.criticality}
            value={draft.criticality}
            allowBlank
            onChange={(v) => onChange({ criticality: (v || null) as DraftTask['criticality'] })}
          />
          <Select
            label="Impact"
            options={enums.impact_size}
            value={draft.impact_size}
            allowBlank
            onChange={(v) => onChange({ impact_size: (v || null) as DraftTask['impact_size'] })}
          />

          <label>
            <span>Due date</span>
            <input
              type="date"
              value={draft.due_date ?? ''}
              onChange={(e) => onChange({ due_date: e.target.value || null })}
            />
          </label>
          <label>
            <span>Project</span>
            <input
              value={draft.project ?? ''}
              onChange={(e) => onChange({ project: e.target.value || null })}
            />
          </label>
          <label>
            <span>Assignee</span>
            <input
              value={draft.assignee ?? ''}
              onChange={(e) => onChange({ assignee: e.target.value || null })}
            />
          </label>
          {customFields.map((field) => (
            <label key={field.field_key}>
              <span>
                {field.label}
                {field.is_required && ' *'}
              </span>
              <select
                value={draft.custom_fields[field.field_key] ?? ''}
                onChange={(e) =>
                  onChange({
                    custom_fields: {
                      ...draft.custom_fields,
                      [field.field_key]: e.target.value,
                    },
                  })
                }
              >
                <option value="">— set —</option>
                {field.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label || o.value}
                  </option>
                ))}
              </select>
            </label>
          ))}

          <label>
            <span>Labels</span>
            <input
              value={draft.labels.join(', ')}
              placeholder="comma separated"
              onChange={(e) =>
                onChange({
                  labels: e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
        </div>

        <div className="toolbar modal-foot">
          <span className="env">
            {draft.source_provider} · {draft.source_ref}
            {draft.existing_task_id && ' · already imported, this will update it'}
          </span>
          {draft.raw_payload && (
            <button className="linkish" onClick={() => setShowRaw((s) => !s)}>
              {showRaw ? 'Hide' : 'Show'} source data
            </button>
          )}
          <span className="spacer" />
          <button className="linkish" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={blocked || busy} onClick={onCommit}>
            {draft.existing_task_id ? 'Update task' : 'Commit task'}
          </button>
        </div>

        {showRaw && draft.raw_payload && (
          <pre className="raw">{JSON.stringify(draft.raw_payload, null, 2)}</pre>
        )}
      </div>
    </div>
  )
}

function Select({
  label,
  options,
  value,
  onChange,
  allowBlank = false,
}: {
  label: string
  options: string[] | undefined
  value: string | null
  onChange: (value: string) => void
  allowBlank?: boolean
}) {
  return (
    <label>
      <span>{label}</span>
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        {allowBlank && <option value="">— set —</option>}
        {(options ?? []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  )
}
