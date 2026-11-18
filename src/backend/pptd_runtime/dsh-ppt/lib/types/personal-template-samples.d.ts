import type { PptdProject, PptdProjectSource } from './pptd.js';
import type { PersonalTemplateProfile } from './personal-template-profile.js';
export interface PersonalTemplateSamples {
  readonly version: number;
  readonly simplifiedTextCount: number;
  readonly representativePages: readonly number[];
  readonly layouts: readonly {
    slideNumber: number;
    role: 'cover' | 'agenda' | 'section' | 'closing' | 'content' | 'multi-block' | 'visual' | 'data';
    content: 'sample' | 'source';
    representative: boolean;
  }[];
}
export declare const PERSONAL_TEMPLATE_SAMPLE_VERSION: number;
export declare function createPersonalTemplateSamples(project: PptdProject, profile: PersonalTemplateProfile): { source: PptdProjectSource; samples: PersonalTemplateSamples };
export declare function validPersonalTemplateSamples(samples: unknown, count: number): samples is PersonalTemplateSamples;
