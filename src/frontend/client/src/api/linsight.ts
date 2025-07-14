import request from "./request";

// 灵思
export function getTools(name: string): Promise<any> {
  return request.get('/api/v1/download?object_name=' + name);
}

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
  });
}

// 获取灵思任务信息
export function getLinsightTaskList(versionId: string): Promise<any> {
  return request.get('/api/v1/linsight/workbench/execute-task-detail', {
    params: {
      session_version_id: versionId
    },
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
  return request.post('/api/v1/linsight/workbench/submit-feedback', { linsight_session_version_id: versionid, ...data }
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