import { LinsightInfo } from "~/store/linsight";
import request from "./request";

// 保存修改sop
export function saveSop(data: {
  sop_content: string,
  linsight_session_version_id: string,
}): Promise<any> {
  return request.post('/api/v1/linsight/workbench/sop-modify', data);
}

// 获取灵思会话信息
export function getLinsightSessionVersionList(ConversationId: string): Promise<any> {
  return request.get('/api/v1/linsight/workbench/session-version-list', {
    params: {
      session_id: ConversationId
    },
  }).then(res => {
    return res.data.map(item => {
      return {
        ...item,
        sop: item.sop?.replace(/^---/, '')?.replace(/\`\`\`markdown/g, '```') ?? '' // 去除markdown标记，否则vditor编辑器会显示为代码块
      }
    }
    )
  });
}

// 获取灵思任务信息
export function getLinsightTaskList(versionId: string, linsight: LinsightInfo): Promise<any> {
  return request.get('/api/v1/linsight/workbench/execute-task-detail', {
    params: {
      session_version_id: versionId
    },
  }).then(res => {
    if (linsight.status === 'terminated') {
      // 任务手动终止后，后端返回的数据status为in_progress的任务，需要修改为terminated
      return res.data.map(item => ({
        ...item,
        status: item.status === 'in_progress' ? 'terminated' : item.status
      }))
    }
    return res.data
  });
}


// 开始执行灵思
export function startLinsight(versionId: string): Promise<any> {
  return request.post('/api/v1/linsight/workbench/start-execute', {
    linsight_session_version_id: versionId
  });
}

// 用户任务中输入事件
export function userInputLinsightEvent(session_version_id: string, linsight_execute_task_id: string, input_content: string): Promise<any> {
  return request.post('/api/v1/linsight/workbench/user-input', {
    session_version_id,
    linsight_execute_task_id,
    input_content
  });
}

// 用户终止任务事件
export function userStopLinsightEvent(linsight_session_version_id: string): Promise<any> {
  return request.post('/api/v1/linsight/workbench/terminate-execute', {
    linsight_session_version_id
  });
}

// 反馈
export function submitLinsightFeedback(versionid, data: {
  feedback: string,
  score: number,
  is_reexecute: boolean,
  cancel_feedback: boolean
}): Promise<any> {
  return request.post('/api/v1/linsight/workbench/submit-feedback',
    { linsight_session_version_id: versionid, ...data },
    { showError: true }
  )
}


// 获取灵思工具
export function getLinsightTools(): Promise<any> {
  return request.get('/api/v1/tool/linsight/preset');
}


// 获取个人知识库信息
export function getPersonalKnowledgeInfo(): Promise<any> {
  return request.get('/api/v1/knowledge/personal_knowledge_info');
}

// 获取组织知识库
export function getKnowledgeInfo(): Promise<any> {
  return request.get('/api/v1/knowledge?page_num=1&page_size=200&type=0');
}

// 获取linsight剩余次数
export function inviteCode() {
  return request.get('/api/v1/invite/code');
};

// 绑定邀请码
export function bindInviteCode(code: string) {
  return request.post('/api/v1/invite/bind', { code });
}

// 批量下载
export async function batchDownload(data: {
  fileName: string,
  files: { file_name: string, file_url: string }[]
}) {
  const res = await request.post('/api/v1/linsight/workbench/batch-download-files', {
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
}

// 检查文件解析状态
export function checkFileParseStatus(ids: string[]) {
  return request.post('/api/v1/linsight/workbench/file-parsing-status', {
    file_ids: ids
  })
}

// 检查sop排队状态
export function checkSopQueueStatus(id: string) {
  return request.get('/api/v1/linsight/workbench/queue-status', {
    params: {
      session_version_id: id
    }
  })
}

// Selected Cases
export function getFeaturedCases(page: number): Promise<any> {
  return request.get('/api/v1/linsight/sop/showcase', {
    params: {
      page,
      page_size: 12
    }
  });
}

// Get case details based on SOP ID
export function getCaseDetail(sop_id: string): Promise<any> {
  return request.get('/api/v1/linsight/sop/showcase/result', {
    params: {
      sop_id
    }
  })
}