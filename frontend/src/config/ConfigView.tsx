import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AppConfig, FieldConfig, FieldOption } from '../api/types'
import { MappingPanel } from './MappingPanel'

/**
 * Config screen: what the dropdowns offer, and what each import flow pre-fills.
 *
 * Everything here is read by the review UI and the filters, so adding an option
 * or a whole field takes effect immediately with no code change.
 */
export function ConfigView({ onChanged }: { onChanged: () => void }) {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setConfig(await api.config())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  async function run(action: () => Promise<unknown>) {
    try {
      await action()
      await reload()
      onChanged()
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  if (error && !config) return <div className="panel error">{error}</div>
  if (!config) return <div className="panel empty">Loading…</div>

  return (
    <div className="stack">
      {error && <div className="panel error">{error}</div>}

      <div className="panel">
        <div className="toolbar">
          <strong>Fields</strong>
          <span className="env">
            These drive every dropdown in review, and the filters on the other tabs.
          </span>
        </div>

        {config.fields.map((field) => (
          <FieldEditor
            key={field.field_key}
            field={field}
            onSave={(next) => run(() => api.saveField(next))}
            onDelete={() => run(() => api.deleteField(field.field_key))}
          />
        ))}

        <NewField onCreate={(next) => run(() => api.saveField(next))} />
      </div>

      <MappingPanel config={config} onSaved={() => void reload()} />

      <DefaultsPanel config={config} onSet={(s, f, v) => run(() => api.setDefault(s, f, v))} />
    </div>
  )
}

function FieldEditor({
  field,
  onSave,
  onDelete,
}: {
  field: FieldConfig
  onSave: (field: Omit<FieldConfig, 'kind' | 'values_locked'>) => void
  onDelete: () => void
}) {
  const [draft, setDraft] = useState(field)
  const [open, setOpen] = useState(false)

  useEffect(() => setDraft(field), [field])

  const dirty = JSON.stringify(draft) !== JSON.stringify(field)

  function setOption(index: number, patch: Partial<FieldOption>) {
    setDraft((d) => ({
      ...d,
      options: d.options.map((o, i) => (i === index ? { ...o, ...patch } : o)),
    }))
  }

  function move(index: number, by: number) {
    const target = index + by
    if (target < 0 || target >= draft.options.length) return
    const options = [...draft.options]
    ;[options[index], options[target]] = [options[target], options[index]]
    setDraft((d) => ({ ...d, options }))
  }

  return (
    <div className="field-editor">
      <div className="toolbar">
        <button className="linkish" onClick={() => setOpen((o) => !o)}>
          {open ? '▾' : '▸'} {field.label}
        </button>
        <span className="pill">{field.kind}</span>
        {!field.enabled && <span className="pill">hidden</span>}
        {field.is_required && <span className="pill">required</span>}
        <span className="env">{field.options.map((o) => o.label || o.value).join(' · ')}</span>
      </div>

      {open && (
        <div className="field-body">
          <div className="filter-row">
            <label className="facet">
              <span>Label</span>
              <input
                value={draft.label}
                onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))}
              />
            </label>
            <label className="facet">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))}
              />
              <span>Shown in review and filters</span>
            </label>
            <label className="facet">
              <input
                type="checkbox"
                checked={draft.is_required}
                onChange={(e) => setDraft((d) => ({ ...d, is_required: e.target.checked }))}
              />
              <span>Required before commit</span>
            </label>
          </div>

          {field.values_locked && (
            <p className="env note">
              This is a builtin scale. You can rename, reorder and hide options, but the
              values themselves are fixed — the watch score's weights and every adapter's
              mapping table are keyed on them, so a new value would silently score zero and
              map from nothing.
            </p>
          )}

          <table className="tasks review options-table">
            <thead>
              <tr>
                <th>Value</th>
                <th>Label</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {draft.options.map((option, i) => (
                <tr key={`${option.value}-${i}`}>
                  <td>
                    <input
                      value={option.value}
                      disabled={field.values_locked}
                      onChange={(e) => setOption(i, { value: e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      value={option.label ?? ''}
                      placeholder={option.value}
                      onChange={(e) => setOption(i, { label: e.target.value })}
                    />
                  </td>
                  <td className="option-actions">
                    <button className="linkish" onClick={() => move(i, -1)} aria-label="Move up">
                      ↑
                    </button>
                    <button className="linkish" onClick={() => move(i, 1)} aria-label="Move down">
                      ↓
                    </button>
                    <button
                      className="linkish"
                      aria-label="Remove option"
                      onClick={() =>
                        setDraft((d) => ({
                          ...d,
                          options: d.options.filter((_, k) => k !== i),
                        }))
                      }
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="toolbar">
            {!field.values_locked && (
              <button
                className="linkish"
                onClick={() =>
                  setDraft((d) => ({ ...d, options: [...d.options, { value: '', label: '' }] }))
                }
              >
                + add option
              </button>
            )}
            <span className="spacer" />
            {field.kind === 'custom' && (
              <button className="linkish danger" onClick={onDelete}>
                Delete field
              </button>
            )}
            <button
              className="primary"
              disabled={!dirty}
              onClick={() =>
                onSave({
                  field_key: draft.field_key,
                  label: draft.label,
                  options: draft.options,
                  enabled: draft.enabled,
                  is_required: draft.is_required,
                  sort_order: draft.sort_order,
                })
              }
            >
              Save
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function NewField({
  onCreate,
}: {
  onCreate: (field: Omit<FieldConfig, 'kind' | 'values_locked'>) => void
}) {
  const [label, setLabel] = useState('')
  const [options, setOptions] = useState('')

  const parsed = options
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  return (
    <div className="field-editor new-field">
      <div className="filter-row">
        <label className="facet">
          <span>New field</span>
          <input
            value={label}
            placeholder="Type, Platform…"
            onChange={(e) => setLabel(e.target.value)}
          />
        </label>
        <label className="facet grow">
          <span>Options</span>
          <input
            value={options}
            placeholder="Bug, Feature, Chore"
            onChange={(e) => setOptions(e.target.value)}
          />
        </label>
        <button
          className="primary"
          disabled={!label.trim() || parsed.length === 0}
          onClick={() => {
            onCreate({
              field_key: label.trim().toLowerCase().replace(/\s+/g, '_'),
              label: label.trim(),
              options: parsed.map((value) => ({ value, label: value })),
              enabled: true,
              is_required: false,
              sort_order: 100,
            })
            setLabel('')
            setOptions('')
          }}
        >
          Add field
        </button>
      </div>
      <p className="env">
        Custom fields need no migration and no code change — they are stored per task and
        appear in the review screen straight away.
      </p>
    </div>
  )
}

function DefaultsPanel({
  config,
  onSet,
}: {
  config: AppConfig
  onSet: (source: string, fieldKey: string, value: string | null) => void
}) {
  const [source, setSource] = useState(config.sources[0] ?? '')

  const current = (fieldKey: string) =>
    config.defaults.find((d) => d.source_provider === source && d.field_key === fieldKey)?.value ??
    ''

  if (!source) return null

  return (
    <div className="panel">
      <div className="toolbar">
        <strong>Defaults per import flow</strong>
        <span className="env">
          Applied before review, and only where the source left the field blank — a source is
          authoritative for what it actually knows. Every default is announced on the draft, and
          the reviewer can still change it.
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

      <div className="mapping-grid">
        {config.fields
          .filter((f) => f.enabled)
          .map((field) => (
            <label key={field.field_key}>
              <span>{field.label}</span>
              <select
                value={current(field.field_key)}
                onChange={(e) => onSet(source, field.field_key, e.target.value || null)}
              >
                <option value="">— no default —</option>
                {field.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label || o.value}
                  </option>
                ))}
              </select>
            </label>
          ))}

        {config.defaultable_extra_keys.map((key) => (
          <label key={key}>
            <span>{key}</span>
            <input
              defaultValue={current(key)}
              placeholder="— no default —"
              onBlur={(e) => {
                const value = e.target.value.trim()
                if (value !== current(key)) onSet(source, key, value || null)
              }}
            />
          </label>
        ))}
      </div>
    </div>
  )
}
