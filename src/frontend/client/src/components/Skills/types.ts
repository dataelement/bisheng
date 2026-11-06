/** 技能 module home: 我的技能 by default, `?view=square` is the 技能广场, `?skill=<id>` opens a detail. */
export const skillCenterPath = "/capabilities?type=skill";
export const skillSquarePath = skillCenterPath;
export function skillDetailPath(skill: { id: number | string; source?: "personal" | "platform" }): string {
  return `${skillCenterPath}&skill=${encodeURIComponent(skill.id)}`;
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
  resourceId?: number;
  id: string;
  scope: string;
  source: "personal";
  enabled: boolean;
  updatedAt: string;
  revision: string;
  file: Blob;
}

export interface PlatformSkill {
  resourceId?: number;
  id: string;
  name: string;
  displayName: string;
  description: string;
  source: 'platform';
  builtinKey?: string | null;
  searchText?: string;
  enabled: boolean;
}

export type CenterSkill = PersonalSkill | PlatformSkill;

/** One row from the skill-center or task-candidate API. */
export interface SkillRecord {
  id: number;
  name: string;
  displayName: string;
  description: string;
  source: "personal" | "platform";
  enabled: boolean;
  builtinKey?: string | null;
  searchText?: string;
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
    this.name = "SkillError";
  }
}
