// Runtime config is loaded before the app so deployments can retain their preview setting across builds.
export const skillCenterPreviewEnabled =
  (typeof window === 'undefined' ? undefined : window.APP_CONFIG?.skillCenterPreviewEnabled) ??
  (import.meta.env.VITE_SKILL_CENTER_PREVIEW === 'true');
/** 技能中心: the skills this account can use; `?skill=<id>` opens one skill's detail. */
export const skillCenterPath = '/skills';

/** Deep link to one skill's detail dialog, personal or enterprise alike. */
export function skillDetailPath(skill: { id: string }): string {
  return `${skillCenterPath}?skill=${encodeURIComponent(skill.id)}`;
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
