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
  | 'linsight_skill'

export type SubjectType = 'user' | 'department' | 'user_group'

export interface SelectedSubject {
  type: SubjectType
  id: number
  name: string
  externalId?: string | null
  departmentPath?: string
  departmentTreePath?: string
  include_children?: boolean
}
