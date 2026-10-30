import type { CenterSkill, PlatformSkill } from './types';

type Translate = (key: string, options: { defaultValue: string }) => string;

/** Resolve display copy from server-owned provenance on each render. */
export function localizeSkill(skill: PlatformSkill, translate: Translate): PlatformSkill {
  if (!skill.builtinKey) return skill;
  return {
    ...skill,
    displayName: translate(`com_builtin_skills.${skill.builtinKey}.name`, { defaultValue: skill.displayName }),
    description: translate(`com_builtin_skills.${skill.builtinKey}.description`, { defaultValue: skill.description }),
    searchText: `${skill.displayName} ${skill.description}`,
  };
}

export function matchesSkillSearch(skill: CenterSkill, query: string): boolean {
  const original = skill.source === 'platform' ? skill.searchText ?? '' : '';
  return `${skill.displayName} ${skill.description} ${skill.name} ${original}`
    .toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}
