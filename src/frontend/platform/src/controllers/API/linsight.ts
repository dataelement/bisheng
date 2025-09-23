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
    return axios.get(`/api/v1/linsight/sop/showcase/result`, { params: data });
  },
}