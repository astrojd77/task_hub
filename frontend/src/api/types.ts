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
  config_schema: Record<string, unknown>
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

export interface Health {
  status: string
  app: string
  environment: string
  db_dialect: string
}
