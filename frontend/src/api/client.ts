import type {
  AppConfig,
  CommitResult,
  DraftBatch,
  DraftTask,
  EnumCatalog,
  Health,
  DestinationResolution,
  FieldConfig,
  MappableInput,
  Providers,
  PushResult,
  Route,
  Task,
  WatchOut,
} from './types'

export class ApiError extends Error {
  status: number
  detail?: unknown

  constructor(message: string, status: number, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail: unknown
    try {
      detail = await res.json()
    } catch {
      detail = await res.text()
    }
    throw new ApiError(
      `${init?.method ?? 'GET'} ${path} failed (${res.status})`,
      res.status,
      detail,
    )
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/** Repeated keys, so ?project=A&project=B works with FastAPI's list params. */
export type TaskQuery = Record<string, string | string[] | undefined>

function toQueryString(query: TaskQuery = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue
    for (const v of Array.isArray(value) ? value : [value]) {
      if (v !== '') params.append(key, v)
    }
  }
  const s = params.toString()
  return s ? `?${s}` : ''
}

/**
 * Ask a source to parse its input into drafts. Nothing is persisted by this
 * call — committing is a separate, explicit step.
 *
 * Always multipart, so file-based sources (csv, email) and config-only ones
 * (jira) share a single request shape.
 */
async function buildDrafts(
  sourceId: string,
  file: File | null,
  config: Record<string, unknown> = {},
): Promise<DraftBatch> {
  const form = new FormData()
  if (file) form.append('file', file)
  form.append('config', JSON.stringify(config))

  const res = await fetch(`/api/sources/${sourceId}/drafts`, {
    method: 'POST',
    body: form, // no Content-Type: the browser sets the multipart boundary
  })
  if (!res.ok) {
    let detail: unknown
    try {
      detail = (await res.json())?.detail
    } catch {
      detail = await res.text()
    }
    throw new ApiError(
      typeof detail === 'string' ? detail : `Import failed (${res.status})`,
      res.status,
      detail,
    )
  }
  return res.json() as Promise<DraftBatch>
}

export const api = {
  buildDrafts,
  health: () => request<Health>('/health'),
  enums: () => request<EnumCatalog>('/enums'),
  providers: () => request<Providers>('/providers'),

  listTasks: (query?: TaskQuery) => request<Task[]>(`/tasks${toQueryString(query)}`),
  getTask: (id: string) => request<Task>(`/tasks/${id}`),
  facets: () => request<Record<string, string[]>>('/tasks/facets'),
  watch: (query?: TaskQuery) => request<WatchOut>(`/watch${toQueryString(query)}`),
  deleteTask: (id: string) =>
    request<void>(`/tasks/${id}`, { method: 'DELETE' }),

  // -- field configuration -------------------------------------------
  config: () => request<AppConfig>('/config'),
  saveField: (field: Omit<FieldConfig, 'kind' | 'values_locked'>) =>
    request<FieldConfig>(`/config/fields/${field.field_key}`, {
      method: 'PUT',
      body: JSON.stringify(field),
    }),
  /** Teach one value from the review screen; merges with existing rules. */
  addValueRule: (
    sourceProvider: string,
    fieldKey: string,
    nativeValue: string,
    value: string,
  ) =>
    request<unknown>('/config/mappings/rule', {
      method: 'POST',
      body: JSON.stringify({
        source_provider: sourceProvider,
        field_key: fieldKey,
        native_value: nativeValue,
        value,
      }),
    }),

  saveMappings: (
    sourceProvider: string,
    mappings: Record<string, { source_expr: string | null; value_map: Record<string, string> }>,
  ) =>
    request<unknown>('/config/mappings', {
      method: 'PUT',
      body: JSON.stringify({ source_provider: sourceProvider, mappings }),
    }),

  /**
   * Ask a source what it can feed a field from. POST because CSV cannot answer
   * without the file — its inputs are that file's columns.
   */
  mappableInputs: async (sourceId: string, file?: File | null): Promise<MappableInput[]> => {
    const form = new FormData()
    if (file) form.append('file', file)
    form.append('config', '{}')
    const res = await fetch(`/api/sources/${sourceId}/inputs`, { method: 'POST', body: form })
    if (!res.ok) return []
    return res.json() as Promise<MappableInput[]>
  },

  deleteField: (fieldKey: string) =>
    request<void>(`/config/fields/${fieldKey}`, { method: 'DELETE' }),
  setDefault: (sourceProvider: string, fieldKey: string, value: string | null) =>
    request<unknown>('/config/defaults', {
      method: 'PUT',
      body: JSON.stringify({
        source_provider: sourceProvider,
        field_key: fieldKey,
        value,
      }),
    }),

  // -- routing (phase 6) --------------------------------------------
  routes: () => request<Route[]>('/routes'),
  setRoute: (project: string, destination: string | null) =>
    request<Route | null>('/routes', {
      method: 'PUT',
      body: JSON.stringify({ project, destination }),
    }),
  taskDestination: (id: string) =>
    request<DestinationResolution>(`/tasks/${id}/destination`),
  setTaskDestination: (id: string, destination: string | null) =>
    request<Task>(`/tasks/${id}/destination`, {
      method: 'PUT',
      body: JSON.stringify({ destination }),
    }),
  pushTask: (id: string) => request<PushResult>(`/tasks/${id}/push`, { method: 'POST' }),

  /** The only way tasks enter the store. */
  commit: (drafts: DraftTask[], defaultDestination?: string) =>
    request<CommitResult>('/commit', {
      method: 'POST',
      body: JSON.stringify({ drafts, default_destination: defaultDestination }),
    }),
}
