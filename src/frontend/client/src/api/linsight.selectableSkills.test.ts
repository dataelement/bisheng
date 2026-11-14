import request from './request';
import { getSelectableSkills } from './linsight';
import { getClientEnvironment, type ClientEnvironment } from '~/utils/clientEnvironment';

jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));
jest.mock('~/utils/clientEnvironment', () => ({ getClientEnvironment: jest.fn() }));

const environment = (channel: ClientEnvironment['channel']): ClientEnvironment => ({
  channel,
  deviceType: 'desktop',
  os: 'macos',
  sources: { channel: 'default', deviceType: 'default', os: 'default' },
  capabilities: { hasNativePresentation: channel === 'desktop', hasHostChatHeader: false },
});

const skills = [
  { name: 'bisheng-pptx', display_name: 'PPT', description: '', default_checked: true },
  { name: 'html-report', display_name: 'HTML report', description: '' },
];

beforeEach(() => {
  jest.mocked(request.get).mockResolvedValue({ status_code: 200, data: skills });
});

it('hides the PPT skill in the desktop client, including when it is preselected', async () => {
  jest.mocked(getClientEnvironment).mockReturnValue(environment('desktop'));

  await expect(getSelectableSkills()).resolves.toEqual([skills[1]]);
});

it('keeps every skill in the web client', async () => {
  jest.mocked(getClientEnvironment).mockReturnValue(environment('web'));

  await expect(getSelectableSkills()).resolves.toEqual(skills);
});
