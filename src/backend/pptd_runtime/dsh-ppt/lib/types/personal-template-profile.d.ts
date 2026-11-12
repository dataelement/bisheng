import type { PptdProject, PptdProjectSource } from './pptd.js';
import type { OfficePalette } from './protocol.js';
export interface PersonalTemplateSlot {
  readonly elementId: string;
  readonly kind: 'text' | 'image' | 'chart' | 'table';
  readonly role: 'title' | 'body' | 'footer' | 'background' | 'image' | 'chart' | 'table';
  readonly action: 'replace-content' | 'review-branding';
  readonly bounds: readonly number[];
  readonly fontFace?: string;
  readonly fontSize?: number;
  readonly color?: string;
  readonly bold?: boolean;
  readonly wrap?: boolean;
  readonly fit?: string;
  readonly textCapacity?: number;
}
export interface PersonalTemplatePageProfile {
  readonly slideNumber: number;
  readonly file: string;
  readonly role: 'cover' | 'data' | 'visual' | 'multi-block' | 'content';
  readonly roleBasis: 'geometry';
  readonly slots: readonly PersonalTemplateSlot[];
}
export interface PersonalTemplateProfile {
  readonly version: number;
  readonly canvas: { readonly width: number; readonly height: number };
  readonly palette: OfficePalette;
  readonly typography: Readonly<Record<'title' | 'body', { readonly fontFace: string; readonly fontSize: number; readonly color: string; readonly bold: boolean }>>;
  readonly pages: readonly PersonalTemplatePageProfile[];
}
export declare const PERSONAL_TEMPLATE_PROFILE_VERSION: number;
export declare function extractPersonalTemplateProfile(project: PptdProject): PersonalTemplateProfile;
export declare function personalTemplateSourceTheme<T extends Pick<PptdProjectSource, 'manifest'>>(source: T, profile: PersonalTemplateProfile): T;
export declare function personalTemplatePageSummary(page: PersonalTemplatePageProfile, detailed?: boolean): string;
export declare function personalTemplateDesignProfile(template: { readonly templateProfile?: PersonalTemplateProfile; readonly templateSamples?: import('./personal-template-samples.js').PersonalTemplateSamples }): string;
export declare function validPersonalTemplateProfile(profile: unknown, pageIndex: readonly {readonly file: string}[]): profile is PersonalTemplateProfile;
