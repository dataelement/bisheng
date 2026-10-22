import { normalizeApiError } from '@bisheng/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { checkPersonalSkill, getPersonalSkillUsage } from '~/api/skillCenter';
import { SkillUploadDialog } from './SkillUploadDialog';

const copy: Record<string, string> = {
  com_skill_center_upload: 'Upload skill',
  com_skill_center_drop: 'Drop a skill file',
  com_skill_center_choose: 'Choose file',
  com_skill_center_reselect: 'Choose again',
  com_skill_center_cancel: 'Cancel',
  com_skill_center_add: 'Add to my skills',
  com_skill_center_parsing: 'Validating skill file…',
  com_skill_center_error_multiple: 'Upload one skill file at a time.',
  com_skill_center_error_size: 'Choose a non-empty file up to 50 MiB.',
  com_skill_center_error_format: 'Choose a .md, .zip, or .skill file.',
  com_skill_center_formats: 'Supports SKILL.md, .zip, and .skill; upload limit 50 MiB, unpacked limit 200 MiB.',
  com_skill_center_usage: 'Usage',
  com_skill_center_quota_full: 'Personal skill count or storage limit reached. No more skills can be added.',
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
  translateApiErrorMessage: (data: { status_message?: string }) => data?.status_message || 'Validation failed',
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
  const zone = screen.getByText('Drop a skill file').parentElement;
  if (!zone) throw new Error('drop zone missing');
  fireEvent.drop(zone, { dataTransfer: { files: list } });
}

it('accepts one skill file dropped on the upload area', () => {
  openDialog();
  dropOnZone([new File(['# skill'], 'visit.md', { type: 'text/markdown' })]);
  expect(screen.getByText('visit.md')).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('keeps a skill package drop inside the upload dialog', () => {
  const onWindowDrop = jest.fn();
  window.addEventListener('drop', onWindowDrop);
  openDialog();
  dropOnZone([new File(['PK'], 'fresh-glossary-builder.skill')]);
  expect(screen.getByText('fresh-glossary-builder.skill')).toBeVisible();
  expect(onWindowDrop).not.toHaveBeenCalled();
  window.removeEventListener('drop', onWindowDrop);
});

it('rejects a drop that contains more than one file', () => {
  (checkPersonalSkill as jest.Mock).mockClear();
  openDialog();
  dropOnZone([
    new File(['a'], 'one.md', { type: 'text/markdown' }),
    new File(['b'], 'two.md', { type: 'text/markdown' }),
  ]);
  expect(screen.getByRole('alert')).toHaveTextContent('Upload one skill file at a time.');
  expect(screen.queryByText('one.md')).not.toBeInTheDocument();
  expect(checkPersonalSkill).not.toHaveBeenCalled();
});

it('validates a dropped file before add can be used', async () => {
  let release: (value: unknown) => void = () => undefined;
  const pending = new Promise((resolve) => { release = resolve; });
  (checkPersonalSkill as jest.Mock).mockReturnValueOnce(pending);
  openDialog();
  dropOnZone([new File(['# skill'], 'brief.md', { type: 'text/markdown' })]);
  expect(await screen.findByText('Validating skill file…')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Add to my skills' })).toBeDisabled();
  await act(async () => {
    release({ name: 'brief', displayName: 'Brief', description: 'd', size: 8, files: ['SKILL.md'] });
  });
  expect(screen.queryByText('Validating skill file…')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Add to my skills' })).toBeEnabled();
});

it('validates a file chosen from the picker the same way', async () => {
  (checkPersonalSkill as jest.Mock).mockReturnValueOnce(new Promise(() => undefined));
  openDialog();
  const picker = document.querySelector('input[type="file"]');
  if (!(picker instanceof HTMLInputElement)) throw new Error('file input missing');
  const file = new File(['# skill'], 'picked.md', { type: 'text/markdown' });
  const list = Object.assign([file], { item: (index: number) => [file][index] ?? null });
  fireEvent.change(picker, { target: { files: list } });
  expect(await screen.findByText('Validating skill file…')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Add to my skills' })).toBeDisabled();
});

it('rejects a file over 50 MiB before sending it', () => {
  (checkPersonalSkill as jest.Mock).mockClear();
  openDialog();
  expect(screen.getByText('Supports SKILL.md, .zip, and .skill; upload limit 50 MiB, unpacked limit 200 MiB.')).toBeVisible();
  const oversized = new File(['x'], 'skill-199MiB.md', { type: 'text/markdown' });
  Object.defineProperty(oversized, 'size', { value: 50 * 1024 * 1024 + 1 });
  dropOnZone([oversized]);
  expect(screen.getByRole('alert')).toHaveTextContent('Choose a non-empty file up to 50 MiB.');
  expect(checkPersonalSkill).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Add to my skills' })).toBeDisabled();
});

it('shows a single message when the skill count is already full', async () => {
  const usage = getPersonalSkillUsage as jest.Mock;
  usage.mockResolvedValueOnce({ count: 20, usedBytes: 0, countLimit: 20, bytesLimit: 209715200 });
  (checkPersonalSkill as jest.Mock).mockClear();
  openDialog();
  expect(await screen.findByText('Personal skill count or storage limit reached. No more skills can be added.')).toBeVisible();
  dropOnZone([new File(['# skill'], '20-priority-planner.md', { type: 'text/markdown' })]);
  expect(screen.getByText('20-priority-planner.md')).toBeVisible();
  expect(checkPersonalSkill).not.toHaveBeenCalled();
  expect(screen.getAllByRole('alert')).toHaveLength(1);
  expect(screen.getAllByRole('button', { name: 'Choose again' })).toHaveLength(1);
  expect(screen.queryByText('Personal skill count limit reached. Delete a skill before uploading.')).not.toBeInTheDocument();
});

it('replaces the server quota error with the dialog message once usage is known', async () => {
  const usage = getPersonalSkillUsage as jest.Mock;
  const restore = usage.getMockImplementation();
  let release: (value: unknown) => void = () => undefined;
  usage.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
  (checkPersonalSkill as jest.Mock).mockRejectedValueOnce(
    normalizeApiError({ status_code: 11061, status_message: 'Personal skill count limit reached. Delete a skill before uploading.' }, { message: 'Personal skill count limit reached. Delete a skill before uploading.' }),
  );
  openDialog();
  dropOnZone([new File(['# skill'], '20-priority-planner.md', { type: 'text/markdown' })]);
  expect(await screen.findByText('Personal skill count limit reached. Delete a skill before uploading.')).toBeVisible();
  await act(async () => {
    release({ count: 20, usedBytes: 0, countLimit: 20, bytesLimit: 209715200 });
  });
  expect(await screen.findByText('Personal skill count or storage limit reached. No more skills can be added.')).toBeVisible();
  expect(screen.queryByText('Personal skill count limit reached. Delete a skill before uploading.')).not.toBeInTheDocument();
  expect(screen.getAllByRole('alert')).toHaveLength(1);
  usage.mockImplementation(restore);
});

it('keeps add disabled when the file fails validation', async () => {
  (checkPersonalSkill as jest.Mock).mockRejectedValueOnce(normalizeApiError({ status_code: 11051, status_message: 'Skill file validation failed' }, { message: 'Skill file validation failed' }));
  openDialog();
  dropOnZone([new File(['x'], 'bad.md', { type: 'text/markdown' })]);
  expect(await screen.findByRole('alert')).toHaveTextContent('Skill file validation failed');
  expect(screen.queryByText('Validating skill file…')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Add to my skills' })).toBeDisabled();
});
