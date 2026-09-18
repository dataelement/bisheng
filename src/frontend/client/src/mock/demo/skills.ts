/**
 * Sample rows for 我的技能 (see ./index.ts for the layer's rules). Personal skills live in
 * the browser's IndexedDB rather than behind an endpoint, so the axios interceptor cannot
 * reach them; `useSkillCenter` appends these to the store's rows instead, behind the same
 * DEV + opt-in switch. They are never written to the store — a page reload forgets any
 * interaction; their switch is a session-only override and the detail dialog keeps replace / delete off.
 */
import type { PersonalSkill } from '~/components/Skills/types';
import { DEMO_ID_PREFIX } from './ids';
import { isDemoDataEnabled } from './index';
import skills from './skills.json';

export function demoPersonalSkills(scope: string): PersonalSkill[] {
  if (!isDemoDataEnabled()) return [];
  return skills.personal.map((skill) => ({
    id: `${DEMO_ID_PREFIX}skill-${skill.name}`,
    scope,
    source: 'personal',
    name: skill.name,
    displayName: skill.display_name,
    description: skill.description,
    instructions: skill.instructions,
    files: skill.files,
    fileName: skill.file_name,
    size: skill.size,
    enabled: skill.enabled,
    updatedAt: skill.updated_at,
    revision: 'demo',
    file: new Blob([skill.instructions], { type: 'text/markdown' }),
  }));
}
