// Permission module shared TypeScript types

export type ResourceType =
  | 'knowledge_space'
  | 'knowledge_library'
  | 'folder'
  | 'knowledge_file'
  | 'workflow'
  | 'assistant'
  | 'tool'
  | 'channel'
  | 'dashboard'

export type RelationLevel = 'owner' | 'manager' | 'editor' | 'viewer'

export type SubjectType = 'user' | 'department' | 'user_group'

export interface PermissionEntry {
  subject_type: SubjectType
  subject_id: number
  subject_name: string | null
  relation: RelationLevel
  model_id?: string
  model_name?: string
  include_children?: boolean
  // Reserved for F008 inherited permissions
  inherited_from?: string
}

export interface AuthorizeItem {
  subject_type: SubjectType
  subject_id: number
  relation: RelationLevel
  model_id?: string
  include_children?: boolean
}

export type GrantItem = AuthorizeItem
export type RevokeItem = AuthorizeItem

export interface SelectedSubject {
  type: SubjectType
  id: number
  name: string
  include_children?: boolean
}
