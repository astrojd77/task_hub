import { useState } from 'react'
import { api } from '../api/client'
import type { DraftTask, FieldConfig, UnmappedValue } from '../api/types'

/**
 * "This value didn't map — what should it mean?", inline in review.
 *
 * The point is that answering it once is permanent: saving writes a rule to the
 * source's mapping, so the same value translates by itself on every future
 * import. Without this the user retypes the same correction forever, or goes
 * hunting for the Config screen with the offending value already off-screen.
 *
 * The rule is merged into the field's existing rules server-side, so teaching a
 * value never disturbs the input column or the rules already there.
 */
export function UnmappedRule({
  draft,
  unmapped,
  fields,
  onApply,
}: {
  draft: DraftTask
  unmapped: UnmappedValue
  /** Configured fields, for the canonical options this can map onto. */
  fields: FieldConfig[]
  onApply: (patch: Partial<DraftTask>) => void
}) {
  const field = fields.find((f) => f.field_key === unmapped.field_key)
  const options = field?.options ?? []
  const [choice, setChoice] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (options.length === 0) return null

  async function save() {
    if (!choice) return
    setBusy(true)
    setError(null)
    try {
      await api.addValueRule(draft.source_provider, unmapped.field_key, unmapped.native_value, choice)
      // Apply it to the row in front of the user as well as saving the rule —
      // otherwise "mapped" would be true but the row would still look wrong.
      onApply(
        field?.kind === 'custom'
          ? { custom_fields: { ...draft.custom_fields, [unmapped.field_key]: choice } }
          : ({ [unmapped.field_key]: choice } as Partial<DraftTask>),
      )
      setDone(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <span className="ok rule-saved">
        “{unmapped.native_value}” now means {choice} for {draft.source_provider}.
      </span>
    )
  }

  return (
    <span className="unmapped-rule">
      <span className="warn">
        “{unmapped.native_value}” didn’t map to a {field?.label ?? unmapped.label}
      </span>
      <select value={choice} disabled={busy} onChange={(e) => setChoice(e.target.value)}>
        <option value="">— it means —</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label || o.value}
          </option>
        ))}
      </select>
      <button className="linkish" disabled={!choice || busy} onClick={() => void save()}>
        Remember this
      </button>
      {error && <span className="error">{error}</span>}
    </span>
  )
}
