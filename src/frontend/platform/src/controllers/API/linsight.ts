import axios from "../request";

// ============ F035 Track D/I: tenant custom skill management ============

export interface SkillBrief {
  id: number;
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  source: 'manual' | 'sop_migrated';
  create_time?: string;
  update_time?: string;
}

export interface SkillFileEntry {
  path: string;
  size: number;
}

export interface SkillDetail extends SkillBrief {
  preview: string;
  source_text: string;
  files: SkillFileEntry[];
}

export interface SkillPage {
  data: SkillBrief[];
  total: number;
}

export interface SkillFormPayload {
  display_name: string;
  name: string;
  description: string;
  content: string;
}

const SKILL_BASE = '/api/v1/linsight/skill';

// Business-error responses are handled by callers (silent mode) so validation
// copy can be localized; see mapSkillError in the skill components.
export const skillApi = {
  getSkillList: (params: { keyword?: string; enabled?: boolean; page?: number; page_size?: number }): Promise<SkillPage> => {
    return axios.get(SKILL_BASE, { params });
  },

  getSkillDetail: (name: string): Promise<SkillDetail> => {
    return axios.get(`${SKILL_BASE}/${encodeURIComponent(name)}`);
  },

  getSkillFile: (name: string, path: string): Promise<{ path: string; content: string }> => {
    return axios.get(`${SKILL_BASE}/${encodeURIComponent(name)}/file`, { params: { path } });
  },

  createSkillForm: (data: SkillFormPayload): Promise<SkillDetail> => {
    const form = new FormData();
    Object.entries(data).forEach(([k, v]) => form.append(k, v));
    return axios.post(SKILL_BASE, form, { silent: true } as any);
  },

  createSkillUpload: (file: File): Promise<SkillDetail> => {
    const form = new FormData();
    form.append('file', file);
    return axios.post(SKILL_BASE, form, { silent: true } as any);
  },

  // Import a skill from a public GitHub directory URL (must contain SKILL.md at root).
  importSkillFromGithub: (url: string): Promise<SkillDetail> => {
    return axios.post(`${SKILL_BASE}/import-github`, { url }, { silent: true } as any);
  },

  updateSkillForm: (name: string, data: SkillFormPayload): Promise<SkillDetail> => {
    const form = new FormData();
    Object.entries(data).forEach(([k, v]) => form.append(k, v));
    return axios.put(`${SKILL_BASE}/${encodeURIComponent(name)}`, form, { silent: true } as any);
  },

  setSkillStatus: (name: string, enabled: boolean) => {
    return axios.patch(`${SKILL_BASE}/${encodeURIComponent(name)}/status`, { enabled });
  },

  deleteSkill: (name: string) => {
    return axios.delete(`${SKILL_BASE}/${encodeURIComponent(name)}`);
  },

  slugify: (text: string): Promise<{ slug: string }> => {
    return axios.get(`${SKILL_BASE}/slugify`, { params: { text } });
  },
};
