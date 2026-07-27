import { useCallback, useEffect, useState } from 'react'
import { api, type TaskQuery } from '../api/client'

/**
 * One filter model for every view. The task list, the calendar and the watch
 * view expose the same facets, so they share this rather than each growing
 * their own copy and drifting apart — which mirrors the backend, where all
 * three go through services/filters.py.
 */
export interface Filters {
  /** Single-select facets: '' means "all". */
  source: string
  project: string
  assignee: string
  destination: string
  /** Multi-select enum toggles. Empty array means "all". */
  status: string[]
  criticality: string[]
  impact_size: string[]
  priority: string[]
}

export const EMPTY_FILTERS: Filters = {
  source: '',
  project: '',
  assignee: '',
  destination: '',
  status: [],
  criticality: [],
  impact_size: [],
  priority: [],
}

export function toQuery(filters: Filters, extra: TaskQuery = {}): TaskQuery {
  return {
    source: filters.source || undefined,
    project: filters.project || undefined,
    assignee: filters.assignee || undefined,
    destination: filters.destination || undefined,
    status: filters.status.length ? filters.status : undefined,
    criticality: filters.criticality.length ? filters.criticality : undefined,
    impact_size: filters.impact_size.length ? filters.impact_size : undefined,
    priority: filters.priority.length ? filters.priority : undefined,
    ...extra,
  }
}

export function isEmpty(filters: Filters): boolean {
  return (
    !filters.source &&
    !filters.project &&
    !filters.assignee &&
    !filters.destination &&
    filters.status.length === 0 &&
    filters.criticality.length === 0 &&
    filters.impact_size.length === 0 &&
    filters.priority.length === 0
  )
}

export function useFilters() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)

  const set = useCallback(
    <K extends keyof Filters>(key: K, value: Filters[K]) =>
      setFilters((f) => ({ ...f, [key]: value })),
    [],
  )

  const toggle = useCallback((key: 'status' | 'criticality' | 'impact_size' | 'priority', value: string) => {
    setFilters((f) => {
      const current = f[key]
      return {
        ...f,
        [key]: current.includes(value)
          ? current.filter((v) => v !== value)
          : [...current, value],
      }
    })
  }, [])

  const reset = useCallback(() => setFilters(EMPTY_FILTERS), [])

  return { filters, set, toggle, reset }
}

/** Distinct values behind the dropdowns. Refetched when tasks change. */
export function useFacets(revision: number) {
  const [facets, setFacets] = useState<Record<string, string[]>>({})

  useEffect(() => {
    api
      .facets()
      .then(setFacets)
      .catch(() => setFacets({}))
  }, [revision])

  return facets
}
