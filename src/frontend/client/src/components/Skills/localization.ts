import type { SkillRecord } from './types';

type SearchableSkill = Pick<SkillRecord, 'name' | 'displayName' | 'description' | 'source' | 'builtinKey' | 'searchText'>;

type Translate = (key: string, options: { defaultValue: string }) => string;

/** Resolve display copy from server-owned provenance on each render. */
export function localizeSkill<T extends SearchableSkill>(skill: T, translate: Translate): T {
  if (!skill.builtinKey) return skill;
  return {
    ...skill,
    displayName: translate(`com_builtin_skills.${skill.builtinKey}.name`, { defaultValue: skill.displayName }),
    description: translate(`com_builtin_skills.${skill.builtinKey}.description`, { defaultValue: skill.description }),
    searchText: `${skill.displayName} ${skill.description}`,
  };
}

export function matchesSkillSearch(skill: SearchableSkill, query: string): boolean {
  const original = skill.source === 'platform' ? skill.searchText ?? '' : '';
  return `${skill.displayName} ${skill.description} ${skill.name} ${original}`
    .toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}
