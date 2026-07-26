import type {
  CommitResult,
  DraftTask,
  EnumCatalog,
  Health,
  Providers,
  Task,
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

export const api = {
  health: () => request<Health>('/health'),
  enums: () => request<EnumCatalog>('/enums'),
  providers: () => request<Providers>('/providers'),

  listTasks: (query?: TaskQuery) => request<Task[]>(`/tasks${toQueryString(query)}`),
  getTask: (id: string) => request<Task>(`/tasks/${id}`),
  facets: () => request<Record<string, string[]>>('/tasks/facets'),
  deleteTask: (id: string) =>
    request<void>(`/tasks/${id}`, { method: 'DELETE' }),

  /** The only way tasks enter the store. */
  commit: (drafts: DraftTask[], defaultDestination?: string) =>
    request<CommitResult>('/commit', {
      method: 'POST',
      body: JSON.stringify({ drafts, default_destination: defaultDestination }),
    }),
}
