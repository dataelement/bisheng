import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { checkPersonalSkill } from '~/api/skillCenter';
import { SkillRequestError } from './types';
import { SkillUploadDialog } from './SkillUploadDialog';

const copy: Record<string, string> = {
  com_skill_center_upload: '上传技能',
  com_skill_center_drop: '拖入已有的技能文件',
  com_skill_center_choose: '选择文件',
  com_skill_center_reselect: '重新选择',
  com_skill_center_cancel: '取消',
  com_skill_center_add: '添加到我的技能',
  com_skill_center_parsing: '正在校验技能文件…',
  com_skill_center_error_multiple: '每次上传一个技能文件。',
  com_skill_center_usage: '用量',
};

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => copy[key] ?? key,
}));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('bisheng-icons', () => {
  const icons = new Proxy({}, { get: () => () => null });
  return { Outlined: icons, Filled: icons, Colored: icons };
});
jest.mock('~/api/request', () => ({
  translateApiErrorMessage: (data: { status_message?: string }) => data?.status_message || '校验失败',
}));
jest.mock('~/api/skillCenter', () => ({
  getPersonalSkillUsage: jest.fn(async () => ({ count: 0, usedBytes: 0, countLimit: 20, bytesLimit: 209715200 })),
  findPersonalSkillByImport: jest.fn(),
  createPersonalSkill: jest.fn(),
  overwritePersonalSkill: jest.fn(),
  checkPersonalSkill: jest.fn(() => new Promise(() => undefined)),
}));
jest.mock('./useSkillCenter', () => ({
  useSkillCenter: () => ({ refresh: jest.fn() }),
}));

function openDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SkillUploadDialog open onOpenChange={jest.fn()} />
    </QueryClientProvider>,
  );
}

function dropOnZone(files: File[]) {
  const list = Object.assign([...files], {
    item: (index: number) => files[index] ?? null,
  });
  const zone = screen.getByText('拖入已有的技能文件').parentElement;
  if (!zone) throw new Error('drop zone missing');
  fireEvent.drop(zone, { dataTransfer: { files: list } });
}

it('accepts one skill file dropped on the upload area', () => {
  openDialog();
  dropOnZone([new File(['# skill'], 'visit.md', { type: 'text/markdown' })]);
  expect(screen.getByText('visit.md')).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('rejects a drop that contains more than one file', () => {
  (checkPersonalSkill as jest.Mock).mockClear();
  openDialog();
  dropOnZone([
    new File(['a'], 'one.md', { type: 'text/markdown' }),
    new File(['b'], 'two.md', { type: 'text/markdown' }),
  ]);
  expect(screen.getByRole('alert')).toHaveTextContent('每次上传一个技能文件。');
  expect(screen.queryByText('one.md')).not.toBeInTheDocument();
  expect(checkPersonalSkill).not.toHaveBeenCalled();
});

it('validates a dropped file before add can be used', async () => {
  let release: (value: unknown) => void = () => undefined;
  const pending = new Promise((resolve) => { release = resolve; });
  (checkPersonalSkill as jest.Mock).mockReturnValueOnce(pending);
  openDialog();
  dropOnZone([new File(['# skill'], 'brief.md', { type: 'text/markdown' })]);
  expect(await screen.findByText('正在校验技能文件…')).toBeVisible();
  expect(screen.getByRole('button', { name: '添加到我的技能' })).toBeDisabled();
  await act(async () => {
    release({ name: 'brief', displayName: 'Brief', description: 'd', size: 8, files: ['SKILL.md'] });
  });
  expect(screen.queryByText('正在校验技能文件…')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '添加到我的技能' })).toBeEnabled();
});

it('validates a file chosen from the picker the same way', async () => {
  (checkPersonalSkill as jest.Mock).mockReturnValueOnce(new Promise(() => undefined));
  openDialog();
  const picker = document.querySelector('input[type="file"]');
  if (!(picker instanceof HTMLInputElement)) throw new Error('file input missing');
  const file = new File(['# skill'], 'picked.md', { type: 'text/markdown' });
  const list = Object.assign([file], { item: (index: number) => [file][index] ?? null });
  fireEvent.change(picker, { target: { files: list } });
  expect(await screen.findByText('正在校验技能文件…')).toBeVisible();
  expect(screen.getByRole('button', { name: '添加到我的技能' })).toBeDisabled();
});

it('keeps add disabled when the file fails validation', async () => {
  (checkPersonalSkill as jest.Mock).mockRejectedValueOnce(new SkillRequestError(11051, undefined, '技能文件校验失败'));
  openDialog();
  dropOnZone([new File(['x'], 'bad.md', { type: 'text/markdown' })]);
  expect(await screen.findByRole('alert')).toHaveTextContent('技能文件校验失败');
  expect(screen.queryByText('正在校验技能文件…')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '添加到我的技能' })).toBeDisabled();
});
