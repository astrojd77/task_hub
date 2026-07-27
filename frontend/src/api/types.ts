/** Mirrors app/schemas/task.py. Keep in step with the backend. */

export type TaskStatus = 'todo' | 'in_progress' | 'blocked' | 'done'
export type Priority = 'low' | 'medium' | 'high' | 'urgent'
export type Criticality = 'low' | 'medium' | 'high' | 'critical'
export type ImpactSize = 'xs' | 's' | 'm' | 'l' | 'xl'

export interface Task {
  id: string
  title: string
  description: string | null
  status: TaskStatus
  priority: Priority
  criticality: Criticality | null
  impact_size: ImpactSize | null
  due_date: string | null
  assignee: string | null
  project: string | null
  labels: string[]
  source_provider: string
  source_ref: string
  external_refs: Record<string, string>
  destination: string | null
  created_at: string
  updated_at: string
}

/** A parsed-but-uncommitted candidate. Deliberately permissive. */
export interface DraftTask {
  title: string
  description: string | null
  status: TaskStatus
  priority: Priority
  criticality: Criticality | null
  impact_size: ImpactSize | null
  due_date: string | null
  assignee: string | null
  project: string | null
  labels: string[]
  source_provider: string
  source_ref: string
  raw_payload: Record<string, unknown> | null
  warnings: string[]
  /** Set when this draft matches an already-committed task. */
  existing_task_id: string | null
}

export interface DraftBatch {
  source_provider: string
  drafts: DraftTask[]
  warnings: string[]
  /**
   * Adapter-specific, opaque to core. CSV puts its detected columns and
   * mapping here; Jira and email say how the batch wants reviewing.
   */
  meta: {
    /** The adapter decides: one item gets a modal, a query gets the table. */
    review_style?: 'modal' | 'table'
    target?: string
    filename?: string
    columns?: string[]
    row_count?: number
    mappable_fields?: string[]
    mapping?: Record<string, string>
    suggested_mapping?: Record<string, string>
    criticality_field?: string | null
    impact_field?: string | null
  }
}

export interface CommitResult {
  created: number
  updated: number
  tasks: Task[]
  warnings: { index: number; source_ref: string | null; message: string }[]
  errors: { index: number; source_ref: string | null; message: string }[]
}

export interface SourceInfo {
  id: string
  display_name: string
  /** Adapter-declared. The known keys below are read by the import panels. */
  config_schema: Record<string, unknown> & {
    configured?: boolean
    criticality_field?: string | null
    impact_field?: string | null
  }
}

export interface DestinationInfo {
  id: string
  display_name: string
  capabilities: { create: boolean; update: boolean; close: boolean }
  config_schema: Record<string, unknown>
}

export interface Providers {
  sources: SourceInfo[]
  destinations: DestinationInfo[]
}

/** Enum option lists come from the server so the UI never hardcodes a scale. */
export type EnumCatalog = Record<string, string[]>

export interface WatchItem {
  task: Task
  score: number
  /** Why this score — the ranking is never a black box. */
  reasons: string[]
  sections: string[]
}

export interface WatchSection {
  key: string
  label: string
  description: string
  items: WatchItem[]
}

export interface WatchOut {
  today: string
  weights: {
    criticality: Record<string, number>
    impact: Record<string, number>
    overdue: number
    due_within_2_days: number
    due_within_7_days: number
    blocked: number
    due_soon_days: number
  }
  sections: WatchSection[]
}

export interface Route {
  project: string
  destination: string
}

export interface DestinationResolution {
  /** Set explicitly on the task; null means it falls through. */
  explicit: string | null
  resolved: string
  /** Which rule won: 'set on the task', a project default, or 'fallback'. */
  reason: string
  external_refs: Record<string, string>
}

export interface PushResult {
  task_id: string
  destination: string
  external_id: string
  url: string | null
  action: 'created' | 'updated'
  task: Task
}

export interface Health {
  status: string
  app: string
  environment: string
  db_dialect: string
}
