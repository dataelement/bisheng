import request from './request';
import { getSelectableSkills } from './linsight';
import { getClientEnvironment } from '~/utils/clientEnvironment';

jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));
jest.mock('~/utils/clientEnvironment', () => ({ getClientEnvironment: jest.fn() }));

const skills = [
  { name: 'bisheng-pptx', display_name: 'PPT 制作', description: '', default_checked: true },
  { name: 'html-report', display_name: '网页报告', description: '' },
];

beforeEach(() => {
  jest.mocked(request.get).mockResolvedValue({ status_code: 200, data: skills });
});

it('hides the PPT skill in the desktop client, including when it is preselected', async () => {
  jest.mocked(getClientEnvironment).mockReturnValue({ channel: 'desktop' } as any);

  await expect(getSelectableSkills()).resolves.toEqual([skills[1]]);
});

it('keeps every skill in the web client', async () => {
  jest.mocked(getClientEnvironment).mockReturnValue({ channel: 'web' } as any);

  await expect(getSelectableSkills()).resolves.toEqual(skills);
});
