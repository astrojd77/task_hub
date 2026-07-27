import type { EnumCatalog } from '../api/types'
import { isEmpty, type Filters } from './filters'

/**
 * Shared filter controls. Enum scales come from /api/enums and facet values
 * from /api/tasks/facets, so nothing here hardcodes a vocabulary — adding a
 * criticality level or a new source shows up automatically.
 */
export function FilterBar({
  filters,
  facets,
  enums,
  onSet,
  onToggle,
  onReset,
}: {
  filters: Filters
  facets: Record<string, string[]>
  enums: EnumCatalog
  onSet: <K extends keyof Filters>(key: K, value: Filters[K]) => void
  onToggle: (key: 'status' | 'criticality' | 'impact_size' | 'priority', value: string) => void
  onReset: () => void
}) {
  return (
    <div className="panel filterbar">
      <div className="filter-row">
        <Facet
          label="Source"
          value={filters.source}
          options={facets.source ?? []}
          onChange={(v) => onSet('source', v)}
        />
        <Facet
          label="Project"
          value={filters.project}
          options={facets.project ?? []}
          onChange={(v) => onSet('project', v)}
        />
        <Facet
          label="Assignee"
          value={filters.assignee}
          options={facets.assignee ?? []}
          onChange={(v) => onSet('assignee', v)}
        />
        <Facet
          label="Destination"
          value={filters.destination}
          options={facets.destination ?? []}
          onChange={(v) => onSet('destination', v)}
        />
        {!isEmpty(filters) && (
          <button className="linkish reset" onClick={onReset}>
            Clear filters
          </button>
        )}
      </div>

      <div className="filter-row">
        <Toggles
          label="Status"
          options={enums.status ?? []}
          selected={filters.status}
          onToggle={(v) => onToggle('status', v)}
        />
        <Toggles
          label="Criticality"
          options={enums.criticality ?? []}
          selected={filters.criticality}
          onToggle={(v) => onToggle('criticality', v)}
        />
        <Toggles
          label="Impact"
          options={enums.impact_size ?? []}
          selected={filters.impact_size}
          onToggle={(v) => onToggle('impact_size', v)}
        />
      </div>
    </div>
  )
}

function Facet({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  return (
    <label className="facet">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  )
}

function Toggles({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string
  options: string[]
  selected: string[]
  onToggle: (value: string) => void
}) {
  return (
    <div className="toggles">
      <span className="facet-label">{label}</span>
      {options.map((o) => (
        <button
          key={o}
          className={selected.includes(o) ? 'chip small active' : 'chip small'}
          aria-pressed={selected.includes(o)}
          onClick={() => onToggle(o)}
        >
          {o}
        </button>
      ))}
    </div>
  )
}
