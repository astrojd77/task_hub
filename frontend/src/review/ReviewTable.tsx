import type { DraftTask, EnumCatalog, FieldConfig } from '../api/types'

/**
 * The review surface. Source-agnostic on purpose: phases 4 and 5 (Jira, email)
 * reuse this for their multi-result batches, and the single-result modal wraps
 * the same field editors.
 *
 * Every field is editable here — including criticality and impact_size, which
 * sources almost never supply and which this screen exists to capture.
 */

export interface DraftIssue {
  blocking: boolean
  message: string
}

/** Server-authoritative rules, mirrored here only for immediate feedback. */
export function validateDraft(draft: DraftTask): DraftIssue[] {
  const issues: DraftIssue[] = []
  if (!draft.summary.trim())
    issues.push({ blocking: true, message: 'Title is required' })
  if (!draft.due_date)
    issues.push({ blocking: false, message: 'No due date — will not appear on the calendar' })
  if (!draft.criticality || !draft.impact_size)
    issues.push({ blocking: false, message: 'Criticality/impact unset — under-ranks in Watch' })
  return issues
}

export function isCommittable(draft: DraftTask): boolean {
  return !validateDraft(draft).some((i) => i.blocking)
}

interface Props {
  drafts: DraftTask[]
  enums: EnumCatalog
  /** User-configured dropdowns from the Config screen; one column each. */
  customFields?: FieldConfig[]
  selected: Set<number>
  onToggle: (index: number) => void
  onToggleAll: (checked: boolean) => void
  onChange: (index: number, patch: Partial<DraftTask>) => void
}

export function ReviewTable({
  drafts,
  enums,
  customFields = [],
  selected,
  onToggle,
  onToggleAll,
  onChange,
}: Props) {
  const selectableCount = drafts.filter(isCommittable).length
  const allSelected = selectableCount > 0 && selected.size === selectableCount

  return (
    <div className="review-scroll">
      <table className="tasks review">
        <thead>
          <tr>
            <th className="col-check">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={(e) => onToggleAll(e.target.checked)}
                aria-label="Select all valid rows"
              />
            </th>
            <th>Title *</th>
            <th>Project</th>
            <th>Assignee</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Criticality</th>
            <th>Impact</th>
            <th>Due</th>
            {customFields.map((f) => (
              <th key={f.field_key}>
                {f.label}
                {f.is_required && ' *'}
              </th>
            ))}
            <th>Labels</th>
          </tr>
        </thead>
        <tbody>
          {drafts.map((draft, i) => {
            const issues = validateDraft(draft)
            const blocked = issues.some((x) => x.blocking)
            return (
              <tr key={`${draft.source_ref}-${i}`} className={blocked ? 'row-blocked' : undefined}>
                <td className="col-check">
                  <input
                    type="checkbox"
                    checked={selected.has(i)}
                    disabled={blocked}
                    onChange={() => onToggle(i)}
                    aria-label={`Select row ${i + 1}`}
                  />
                </td>
                <td className="col-summary">
                  <input
                    className={blocked ? 'invalid' : undefined}
                    value={draft.summary}
                    placeholder="Required"
                    onChange={(e) => onChange(i, { summary: e.target.value })}
                  />
                  <RowNotes draft={draft} issues={issues} />
                </td>
                <td>
                  <input
                    value={draft.project ?? ''}
                    onChange={(e) => onChange(i, { project: e.target.value || null })}
                  />
                </td>
                <td>
                  <input
                    value={draft.assignee ?? ''}
                    onChange={(e) => onChange(i, { assignee: e.target.value || null })}
                  />
                </td>
                <EnumCell
                  options={enums.status}
                  value={draft.status}
                  onChange={(v) => onChange(i, { status: v as DraftTask['status'] })}
                />
                <EnumCell
                  options={enums.priority}
                  value={draft.priority}
                  onChange={(v) => onChange(i, { priority: v as DraftTask['priority'] })}
                />
                <EnumCell
                  options={enums.criticality}
                  value={draft.criticality}
                  allowBlank
                  onChange={(v) =>
                    onChange(i, { criticality: (v || null) as DraftTask['criticality'] })
                  }
                />
                <EnumCell
                  options={enums.impact_size}
                  value={draft.impact_size}
                  allowBlank
                  onChange={(v) =>
                    onChange(i, { impact_size: (v || null) as DraftTask['impact_size'] })
                  }
                />
                <td>
                  <input
                    type="date"
                    value={draft.due_date ?? ''}
                    onChange={(e) => onChange(i, { due_date: e.target.value || null })}
                  />
                </td>
                {customFields.map((field) => (
                  <EnumCell
                    key={field.field_key}
                    options={field.options.map((o) => o.value)}
                    value={draft.custom_fields[field.field_key] ?? null}
                    allowBlank
                    onChange={(v) =>
                      onChange(i, {
                        custom_fields: { ...draft.custom_fields, [field.field_key]: v },
                      })
                    }
                  />
                ))}
                <td>
                  <input
                    value={draft.labels.join(', ')}
                    placeholder="comma separated"
                    onChange={(e) =>
                      onChange(i, {
                        labels: e.target.value
                          .split(',')
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function EnumCell({
  options,
  value,
  onChange,
  allowBlank = false,
}: {
  options: string[] | undefined
  value: string | null
  onChange: (value: string) => void
  allowBlank?: boolean
}) {
  return (
    <td>
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        {allowBlank && <option value="">— set —</option>}
        {(options ?? []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </td>
  )
}

function RowNotes({ draft, issues }: { draft: DraftTask; issues: DraftIssue[] }) {
  const notes = [
    ...draft.warnings.map((message) => ({ blocking: false, message, fromSource: true })),
    ...issues.map((i) => ({ ...i, fromSource: false })),
  ]
  if (notes.length === 0) return null
  return (
    <ul className="row-notes">
      {notes.map((n, k) => (
        <li key={k} className={n.blocking ? 'error' : 'warn'}>
          {n.message}
        </li>
      ))}
    </ul>
  )
}
