import http from '~/api/request';

export type ModelRecoveryEntry = 'daily' | 'knowledge' | 'channel';
export type ModelRecoveryAction = 'manual_retry' | 'switch_model';

export type ModelRecoveryTarget =
  | { entry: 'daily' }
  | { entry: 'knowledge'; spaceId: string | number }
  | { entry: 'channel' };

export interface ModelRecoveryCommand {
  executionId: string;
  attemptId: string;
  subjectId: string;
  action: ModelRecoveryAction;
  targetModelId?: string | number;
}

export interface ModelRecoveryResponse {
  execution_id: string;
  attempt_id: string;
  accepted: boolean;
  error_type?: string;
}

interface RecoveryResponseEnvelope {
  status_code: number;
  data?: ModelRecoveryResponse;
}

export interface BuiltModelRecoveryRequest {
  url: string;
  body: {
    attempt_id: string;
    subject_id: string;
    action: ModelRecoveryAction;
    target_model_id?: number;
  };
  streaming: boolean;
}

function recoveryUrl(target: ModelRecoveryTarget, executionId: string): string {
  const encodedExecutionId = encodeURIComponent(executionId);
  switch (target.entry) {
    case 'daily':
      return `/api/v1/workstation/chat/executions/${encodedExecutionId}/recover`;
    case 'knowledge':
      return `/api/v1/knowledge/space/${encodeURIComponent(String(target.spaceId))}/chat/executions/${encodedExecutionId}/recover`;
    case 'channel':
      return `/api/v1/channel/chat/executions/${encodedExecutionId}/recover`;
  }
}

export function buildModelRecoveryRequest(
  target: ModelRecoveryTarget,
  command: ModelRecoveryCommand,
): BuiltModelRecoveryRequest {
  const targetModelId = command.targetModelId == null ? undefined : Number(command.targetModelId);
  return {
    url: recoveryUrl(target, command.executionId),
    body: {
      attempt_id: command.attemptId,
      subject_id: command.subjectId,
      action: command.action,
      ...(targetModelId == null ? {} : { target_model_id: targetModelId }),
    },
    streaming: true,
  };
}

/**
 * Daily, knowledge, and channel callers can use the built request with their
 * existing SSE transports so answer deltas remain streamable.
 */
export async function recoverModelCall(
  target: ModelRecoveryTarget,
  command: ModelRecoveryCommand,
): Promise<ModelRecoveryResponse> {
  const request = buildModelRecoveryRequest(target, command);
  const response = await http.post(request.url, request.body) as RecoveryResponseEnvelope;
  if (response.status_code !== 200 || !response.data) {
    throw new Error('Model recovery request was rejected');
  }
  return response.data;
}
