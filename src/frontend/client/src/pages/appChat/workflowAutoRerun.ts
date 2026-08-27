export interface WorkflowActivation {
  chatId: string;
  handled: boolean;
  handshakeSent: boolean;
}

interface WorkflowCloseMessage {
  category?: string;
  type?: string;
  chat_id?: string;
  message?: unknown;
}

interface WorkflowCloseDecisionInput {
  data: WorkflowCloseMessage;
  activation: WorkflowActivation;
  enabled: boolean;
  isStandaloneWorkflow: boolean;
  isNewConversation: boolean;
}

interface WorkflowRunFlow {
  id: string | number;
  data?: {
    edges?: unknown;
    nodes?: unknown;
    viewport?: unknown;
  };
  [key: string]: unknown;
}

export type WorkflowCloseAction = 'auto' | 'manual' | 'ignore';

export function createWorkflowActivation(chatId: string): WorkflowActivation {
  return { chatId, handled: false, handshakeSent: false };
}

export function syncWorkflowActivation(
  activation: WorkflowActivation,
  chatId: string,
): WorkflowActivation {
  return activation.chatId === chatId ? activation : createWorkflowActivation(chatId);
}

export function claimWorkflowHandshake(
  activation: WorkflowActivation,
  chatId: string,
): boolean {
  if (activation.chatId !== chatId || activation.handshakeSent) return false;
  activation.handshakeSent = true;
  return true;
}

export function isWorkflowFinishedStatusCheck(data: WorkflowCloseMessage): boolean {
  if (data.category !== 'processing' || data.type !== 'close') return false;
  if (!data.message || typeof data.message !== 'object') return false;

  const message = data.message as Record<string, unknown>;
  return message.event === 'workflow_status_checked' && message.status === 'finished';
}

export function decideWorkflowCloseAction({
  data,
  activation,
  enabled,
  isStandaloneWorkflow,
  isNewConversation,
}: WorkflowCloseDecisionInput): WorkflowCloseAction {
  if (data.category !== 'processing' || data.type !== 'close') return 'ignore';

  if (!isWorkflowFinishedStatusCheck(data)) return 'manual';
  if (data.chat_id !== activation.chatId || activation.handled) return 'ignore';

  return enabled && isStandaloneWorkflow && !isNewConversation ? 'auto' : 'manual';
}

export function buildWorkflowInitMessage(flow: WorkflowRunFlow, chatId: string) {
  const { data, ...other } = flow;
  const workflowData = data
    ? { ...other, edges: data.edges, nodes: data.nodes, viewport: data.viewport }
    : other;

  return {
    action: 'init_data',
    chat_id: chatId,
    flow_id: workflowData.id,
    data: workflowData,
  };
}
