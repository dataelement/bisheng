import { getVoice2TextApi, getWorkbenchModelListApi, textToSpeech } from '~/api';
import request from './request';

export type VoiceTarget = { version: 'v1' } | { version: 'v3'; flowId: string };

export type VoiceModels = {
  asr_model?: { id?: string | null } | null;
  tts_model?: { id?: string | null } | null;
};

type VoiceConfigResponse = { data: VoiceModels | { data: VoiceModels } };

const speechOptions: NonNullable<Parameters<typeof request.post>[2]> & { skip403Redirect: boolean } = {
  skip403Redirect: true,
};

function publicVoiceUrl(target: Extract<VoiceTarget, { version: 'v3' }>, suffix = '') {
  if (!target.flowId) throw new Error('A published application is required for speech');
  return `/api/v3/llm/workbench${suffix}?flow_id=${encodeURIComponent(target.flowId)}`;
}

export function getVoiceModels(target: VoiceTarget): Promise<VoiceConfigResponse> {
  return target.version === 'v3'
    ? request.get<VoiceConfigResponse>(publicVoiceUrl(target), speechOptions)
    : getWorkbenchModelListApi();
}

export function selectVoiceModels(response: VoiceConfigResponse): VoiceModels {
  return 'data' in response.data ? response.data.data : response.data;
}

export function transcribeVoice(data: FormData, target: VoiceTarget): Promise<{ data: string }> {
  return target.version === 'v3'
    ? request.postMultiPart(publicVoiceUrl(target, '/asr'), data, speechOptions)
    : getVoice2TextApi(data);
}

export function synthesizeVoice(text: string, target: VoiceTarget): Promise<unknown> {
  return target.version === 'v3'
    ? request.post(publicVoiceUrl(target, '/tts'), { text }, speechOptions)
    : textToSpeech(text);
}

export function readVoiceAudioPath(response: unknown): string {
  let value = response;
  for (let depth = 0; depth < 2; depth += 1) {
    if (typeof value !== 'object' || value === null || !('data' in value)) break;
    value = value.data;
  }
  return typeof value === 'string' ? value : '';
}
