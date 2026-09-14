import { getVoice2TextApi, getWorkbenchModelListApi, textToSpeech } from '~/api';
import request from './request';
import { getVoiceModels, readVoiceAudioPath, selectVoiceModels, synthesizeVoice, transcribeVoice } from './voice';

jest.mock('~/api', () => ({
  getVoice2TextApi: jest.fn(),
  getWorkbenchModelListApi: jest.fn(),
  textToSpeech: jest.fn(),
}));
jest.mock('./request', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), postMultiPart: jest.fn() },
}));

test('guest speech uses v3 with the published application on all requests', async () => {
  const target = { version: 'v3', flowId: 'app-1' } as const;
  const audio = new FormData();
  audio.append('file', new Blob(['recording']), 'recording.wav');
  await getVoiceModels(target);
  await transcribeVoice(audio, target);
  await synthesizeVoice('Read this', target);
  expect(request.get).toHaveBeenCalledWith('/api/v3/llm/workbench?flow_id=app-1', { skip403Redirect: true });
  expect(request.postMultiPart).toHaveBeenCalledWith(
    '/api/v3/llm/workbench/asr?flow_id=app-1', audio, { skip403Redirect: true },
  );
  expect(request.post).toHaveBeenCalledWith(
    '/api/v3/llm/workbench/tts?flow_id=app-1', { text: 'Read this' }, { skip403Redirect: true },
  );
  expect(getVoice2TextApi).not.toHaveBeenCalled();
  expect(getWorkbenchModelListApi).not.toHaveBeenCalled();
  expect(textToSpeech).not.toHaveBeenCalled();
});

test('authenticated speech retains the existing API functions', async () => {
  const target = { version: 'v1' } as const;
  const audio = new FormData();
  await getVoiceModels(target);
  await transcribeVoice(audio, target);
  await synthesizeVoice('Read this', target);
  expect(getWorkbenchModelListApi).toHaveBeenCalledTimes(1);
  expect(getVoice2TextApi).toHaveBeenCalledWith(audio);
  expect(textToSpeech).toHaveBeenCalledWith('Read this');
  expect(request.get).not.toHaveBeenCalled();
  expect(request.post).not.toHaveBeenCalled();
  expect(request.postMultiPart).not.toHaveBeenCalled();
});

test('a guest request without an application never falls back to v1', () => {
  const target = { version: 'v3', flowId: '' } as const;
  expect(() => getVoiceModels(target)).toThrow('published application');
  expect(() => transcribeVoice(new FormData(), target)).toThrow('published application');
  expect(() => synthesizeVoice('Read this', target)).toThrow('published application');
  expect(getWorkbenchModelListApi).not.toHaveBeenCalled();
});

test('configuration supports the public envelope and the existing admin envelope', () => {
  const config = { asr_model: { id: 'asr' }, tts_model: { id: 'tts' } };
  expect(selectVoiceModels({ data: config })).toEqual(config);
  expect(selectVoiceModels({ data: { data: config } })).toEqual(config);
});

test.each(['https://media.example/a.mp3', { data: 'https://media.example/a.mp3' }, { data: { data: 'https://media.example/a.mp3' } }])(
  'reads speech audio from supported response envelopes', (response) => {
    expect(readVoiceAudioPath(response)).toBe('https://media.example/a.mp3');
  },
);
