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
  // F054 hosted applications. Duplicated from
  // controllers/API/permission.ts — keep both in step.
  | 'app'

export type SubjectType = 'user' | 'department' | 'user_group'

export interface SelectedSubject {
  type: SubjectType
  id: number
  name: string
  include_children?: boolean
}
