// Runtime config is loaded before the app so deployments can retain their preview setting across builds.
export const skillCenterPreviewEnabled =
  (typeof window === 'undefined' ? undefined : window.APP_CONFIG?.skillCenterPreviewEnabled) ??
  (import.meta.env.VITE_SKILL_CENTER_PREVIEW === 'true');
/** 技能 module home: 我的技能 by default, `?view=square` is the 技能广场, `?skill=<id>` opens a detail. */
export const skillCenterPath = '/skills';
export const skillSquarePath = `${skillCenterPath}?view=square`;

/** Deep link to one skill's detail sheet. Enterprise skills live in the square view. */
export function skillDetailPath(skill: { id: string; source: 'personal' | 'platform' }): string {
  const params = new URLSearchParams();
  if (skill.source === 'platform') params.set('view', 'square');
  params.set('skill', skill.id);
  return `${skillCenterPath}?${params.toString()}`;
}

export interface SkillManifest {
  name: string;
  displayName: string;
  description: string;
  instructions: string;
  files: string[];
  fileName: string;
  size: number;
}

export interface PersonalSkill extends SkillManifest {
  id: string;
  scope: string;
  source: 'personal';
  enabled: boolean;
  updatedAt: string;
  revision: string;
  file: Blob;
}

export interface PlatformSkill {
  id: string;
  name: string;
  displayName: string;
  description: string;
  source: 'platform';
  enabled: true;
}

export type CenterSkill = PersonalSkill | PlatformSkill;

export class SkillError extends Error {
  constructor(public readonly code: string) {
    super(code);
    this.name = 'SkillError';
  }
}
