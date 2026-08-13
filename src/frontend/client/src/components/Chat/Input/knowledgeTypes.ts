/** Shared shape of a knowledge picker selection (chat input toolbar). */
export type KnowledgeType = 'org' | 'space';

export interface KnowledgeItem {
  id: string;
  name: string;
  type: KnowledgeType;
}
