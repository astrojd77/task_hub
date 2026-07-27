import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AppConfig, FieldConfig, MappableInput } from '../api/types'

/**
 * Field mapping, one import flow at a time.
 *
 * Two halves per field, either usable alone:
 *   from   — which input feeds it (a CSV column, a Jira field, an email part)
 *   values — how that input's values translate into canonical ones
 *
 * Both are overrides. Left blank, the adapter's own header aliases and value
 * tables still apply, so this screen only has to describe what differs.
 *
 * The "from" choices come from the adapter itself via /sources/{id}/inputs, so
 * nobody has to remember that Severity is customfield_10042. CSV can only
 * answer once it has a file, hence the sample-file picker.
 */

export interface MappingDraft {
  source_expr: string | null
  value_map: Record<string, string>
}

export function MappingPanel({
  config,
  onSaved,
}: {
  config: AppConfig
  onSaved: () => void
}) {
  const [source, setSource] = useState(config.sources[0] ?? '')
  const [inputs, setInputs] = useState<MappableInput[]>([])
  const [draft, setDraft] = useState<Record<string, MappingDraft>>({})
  const [sampleName, setSampleName] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // Seed the editor from what is stored for this flow.
  useEffect(() => {
    const stored: Record<string, MappingDraft> = {}
    for (const m of config.mappings) {
      if (m.source_provider === source) {
        stored[m.field_key] = { source_expr: m.source_expr, value_map: m.value_map }
      }
    }
    setDraft(stored)
    setSaved(false)
  }, [config.mappings, source])

  // Jira and email can list their inputs unprompted; CSV needs a file.
  useEffect(() => {
    setInputs([])
    setSampleName(null)
    if (source && source !== 'csv') {
      api
        .mappableInputs(source)
        .then(setInputs)
        .catch(() => setInputs([]))
    }
  }, [source])

  async function loadSample(file: File | null) {
    if (!file) return
    setSampleName(file.name)
    setInputs(await api.mappableInputs(source, file))
  }

  function update(fieldKey: string, patch: Partial<MappingDraft>) {
    setDraft((d) => ({
      ...d,
      [fieldKey]: {
        source_expr: patch.source_expr ?? d[fieldKey]?.source_expr ?? null,
        value_map: patch.value_map ?? d[fieldKey]?.value_map ?? {},
      },
    }))
    setSaved(false)
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.saveMappings(source, draft)
      setSaved(true)
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!source) return null

  // Enum-valued fields are the ones where value rules make sense; free-text
  // fields only need a "from".
  const fields = config.mappable_fields

  return (
    <div className="panel">
      <div className="toolbar">
        <strong>Field mapping</strong>
        <span className="env">
          Which input feeds each field, and how its values translate. Anything left blank falls
          back to the adapter's built-in detection.
        </span>
      </div>

      <div className="source-picker">
        {config.sources.map((s) => (
          <button
            key={s}
            className={s === source ? 'chip active' : 'chip'}
            onClick={() => setSource(s)}
          >
            {s}
          </button>
        ))}
      </div>

      {source === 'csv' && (
        <p className="env note">
          A CSV's inputs are its columns, so they are only knowable from a file.{' '}
          <label className="linkish file-pick">
            Load a sample file
            <input
              type="file"
              accept=".csv,.tsv,text/csv"
              hidden
              onChange={(e) => void loadSample(e.target.files?.[0] ?? null)}
            />
          </label>
          {sampleName && ` — reading columns from ${sampleName}`}
        </p>
      )}

      {source !== 'csv' && inputs.length === 0 && (
        <p className="env note">
          {source === 'jira'
            ? 'Jira is not configured, so its custom fields cannot be listed. You can still type a field id.'
            : 'This source did not report any inputs. You can still type one.'}
        </p>
      )}

      <div className="review-scroll">
        <table className="tasks review mapping-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Read from</th>
              <th>Value rules</th>
            </tr>
          </thead>
          <tbody>
            {fields.map((field) => (
              <MappingRow
                key={field.field_key}
                field={field}
                inputs={inputs}
                value={draft[field.field_key]}
                onChange={(patch) => update(field.field_key, patch)}
              />
            ))}
            {EXTRA_MAPPABLE.map((key) => (
              <MappingRow
                key={key}
                field={{ field_key: key, label: key, options: [] } as unknown as FieldConfig}
                inputs={inputs}
                value={draft[key]}
                freeText
                onChange={(patch) => update(key, patch)}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="toolbar">
        {error && <span className="error">{error}</span>}
        {saved && <span className="ok">Saved — the next import will use this.</span>}
        <span className="spacer" />
        <button className="primary" disabled={busy} onClick={() => void save()}>
          Save mapping for {source}
        </button>
      </div>
    </div>
  )
}

/** Canonical fields that are not dropdowns but are still worth mapping. */
const EXTRA_MAPPABLE = [
  'summary',
  'description',
  'due_date',
  'assignee',
  'project',
  'labels',
  'source_ref',
]

function MappingRow({
  field,
  inputs,
  value,
  freeText = false,
  onChange,
}: {
  field: FieldConfig
  inputs: MappableInput[]
  value: MappingDraft | undefined
  freeText?: boolean
  onChange: (patch: Partial<MappingDraft>) => void
}) {
  const from = value?.source_expr ?? ''
  const rules = Object.entries(value?.value_map ?? {})

  return (
    <tr>
      <td>
        <strong>{field.label}</strong>
        <div className="env">{field.field_key}</div>
      </td>

      <td>
        {inputs.length > 0 ? (
          <select value={from} onChange={(e) => onChange({ source_expr: e.target.value || null })}>
            <option value="">— auto-detect —</option>
            {inputs.map((i) => (
              <option key={i.key} value={i.key}>
                {i.label}
                {i.hint ? ` — ${i.hint}` : ''}
              </option>
            ))}
          </select>
        ) : (
          <input
            value={from}
            placeholder="auto-detect"
            onChange={(e) => onChange({ source_expr: e.target.value || null })}
          />
        )}
      </td>

      <td>
        {freeText ? (
          <span className="env">free text — no value rules</span>
        ) : (
          <ValueRules
            options={field.options?.map((o) => o.value) ?? []}
            rules={rules}
            onChange={(next) => onChange({ value_map: Object.fromEntries(next) })}
          />
        )}
      </td>
    </tr>
  )
}

function ValueRules({
  options,
  rules,
  onChange,
}: {
  options: string[]
  rules: [string, string][]
  onChange: (rules: [string, string][]) => void
}) {
  return (
    <div className="value-rules">
      {rules.map(([native, canonical], i) => (
        <div className="value-rule" key={i}>
          <input
            value={native}
            placeholder="their value"
            onChange={(e) => {
              const next = [...rules]
              next[i] = [e.target.value, canonical]
              onChange(next)
            }}
          />
          <span>→</span>
          <select
            value={canonical}
            onChange={(e) => {
              const next = [...rules]
              next[i] = [native, e.target.value]
              onChange(next)
            }}
          >
            {options.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
          <button
            className="linkish"
            aria-label="Remove rule"
            onClick={() => onChange(rules.filter((_, k) => k !== i))}
          >
            ✕
          </button>
        </div>
      ))}
      {options.length > 0 && (
        <button className="linkish" onClick={() => onChange([...rules, ['', options[0]]])}>
          + add rule
        </button>
      )}
    </div>
  )
}
