/** Skill center home. `?skill=<id>` opens one skill's detail. */
export const skillCenterPath = '/skills';

/** Deep link to one skill's detail dialog. */
export function skillDetailPath(skill: { id: number | string }): string {
  const params = new URLSearchParams();
  params.set('skill', String(skill.id));
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

/** One row from the skill-center or task-candidate API. */
export interface SkillRecord {
  id: number;
  name: string;
  displayName: string;
  description: string;
  source: 'personal' | 'platform';
  enabled: boolean;
  contentHash: string;
  bundleMissing: boolean;
  /** Last change, or the creation time when a row has never been updated. */
  updatedAt: string;
  preview: string;
  /** Raw SKILL.md, including the YAML header. Present on the detail response. */
  sourceText?: string;
  files: string[];
}

export class SkillError extends Error {
  constructor(public readonly code: string) {
    super(code);
    this.name = 'SkillError';
  }
}
