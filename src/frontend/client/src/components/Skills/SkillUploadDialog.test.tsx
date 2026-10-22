import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { SkillUploadDialog } from './SkillUploadDialog';

const copy: Record<string, string> = {
  com_skill_center_upload: '上传技能',
  com_skill_center_drop: '拖入已有的技能文件',
  com_skill_center_choose: '选择文件',
  com_skill_center_reselect: '重新选择',
  com_skill_center_cancel: '取消',
  com_skill_center_add: '添加到我的技能',
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
jest.mock('~/api/skillCenter', () => ({
  getPersonalSkillUsage: jest.fn(async () => ({ count: 0, usedBytes: 0, countLimit: 20, bytesLimit: 209715200 })),
  findPersonalSkillByImport: jest.fn(),
  createPersonalSkill: jest.fn(),
  overwritePersonalSkill: jest.fn(),
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
  openDialog();
  dropOnZone([
    new File(['a'], 'one.md', { type: 'text/markdown' }),
    new File(['b'], 'two.md', { type: 'text/markdown' }),
  ]);
  expect(screen.getByRole('alert')).toHaveTextContent('每次上传一个技能文件。');
  expect(screen.queryByText('one.md')).not.toBeInTheDocument();
});
