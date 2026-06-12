import axios from "../request";

// src/controllers/API.ts
export const sopApi = {
  // 获取SOP列表
  getSopList: (params: { keywords?: string; page?: number; page_size?: number; showcase?: 0 | 1 }) => {
    return axios.get('/api/v1/linsight/sop/list', { params });
  },

  // 添加SOP
  addSop: (data: { name: string; description?: string; content: string; rating?: number }) => {
    return axios.post('/api/v1/linsight/sop/add', data);
  },

  // 更新SOP
  updateSop: (data: { id: string; name: string; description: string; content: string; rating: number }) => {
    return axios.post('/api/v1/linsight/sop/update', data);
  },

  // 删除SOP
  deleteSop: (id: string) => {
    return axios.delete(`/api/v1/linsight/sop/remove`, {
      data: {
        sop_ids: [id]
      }
    });
  },
  // 批量删除SOP
  batchDeleteSop: (sop_ids: string[]) => {
    return axios.delete('/api/v1/linsight/sop/remove', {
      data: { sop_ids }
    });
  },
  // 获取工具列表
  getToolList: () => {
    return axios.get('/api/v1/workstation/config');
  },
  setToolList: (data) => {
    return axios.post(`api/v1/workstation/config`, data);
  },
  GetSopRecord(params: { keyword?: string; page?: number; page_size?: number; sort?: string }) {
    return axios.get('/api/v1/linsight/sop/record', { params });
  },
  SyncSopRecord: (data) => {
    return axios.post(`/api/v1/linsight/sop/record/sync`, data);
  },
  UploadSopRecord: (data) => {
    return axios.post(`/api/v1/linsight/sop/upload`, data);
  },
  // 设为/取消精选
  switchShowcase: (data: { sop_id: string; showcase: boolean }) => {
    return axios.post(`/api/v1/linsight/sop/showcase`, data);
  },
  getSopShowcaseDetail: (data: { sop_id: string; linsight_version_id: string }) => {
    if (!data.sop_id && !data.linsight_version_id) {
      return Promise.reject('缺少必要参数');
    }
    return axios.get(`/api/v1/linsight/sop/showcase/result`, { params: data });
  },
  batchDownload: async (data: {
    fileName: string,
    files: { file_name: string, file_url: string }[]
  }) => {
    const res = await axios.post('/api/v1/linsight/workbench/batch-download-files', {
      zip_name: data.fileName,
      file_info_list: data.files
    }, {
      responseType: 'blob'
    })

    console.log('res :>> ', res);
    const url = window.URL.createObjectURL(new Blob([res]));
    const a = document.createElement('a');
    a.href = url;
    a.download = data.fileName || 'downloadFile.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },
  getLinsightFileDownloadApi: async (fileUrl: string, vid: string): Promise<any> => {
    return axios.post('/api/v1/linsight/workbench/file_download', { file_url: fileUrl, session_version_id: vid });
  }
}
// ============ F035 Track D/I: tenant custom skill management ============

export interface SkillBrief {
  id: number;
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  source: 'manual' | 'sop_migrated';
  create_time?: string;
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
