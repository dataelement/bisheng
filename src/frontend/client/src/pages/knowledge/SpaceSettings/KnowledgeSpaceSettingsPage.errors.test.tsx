import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import i18next from 'i18next';
import messages from '../../../locales/en/api_errors.gen.json';
import { KnowledgeSpaceSettingsPage } from './KnowledgeSpaceSettingsPage';

const mockSubmit = jest.fn();
const mockNavigate = jest.fn();
const mockNotify = jest.fn();
const mockSettings = {
  mode: 'edit', loading: false, loadError: null, canEdit: true, canManagePermissions: false,
  relationModels: [], permissionRows: [], autoTagFeatureVisible: true,
  tagLibraries: [{ id: 1, name: 'Library' }], autoTagPreview: [],
  form: { name: 'Space', description: 'Keep these edits', visibility: 'private', autoTagEnabled: true,
    autoTagMode: 'library', autoTagLibraryId: 1, autoTagCustomText: '' },
  submit: mockSubmit,
};
jest.mock('./useKnowledgeSpaceSettingsForm', () => ({
  useKnowledgeSpaceSettingsForm: () => mockSettings,
  parseKnowledgeSpaceCustomTags: (text: string) => text.split('\n').filter(Boolean),
}));
jest.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useLocation: () => ({ state: { returnPath: '/knowledge' } }),
  useParams: () => ({ spaceId: '4322' }),
}));
jest.mock('~/api/knowledge', () => ({ VisibilityType: { PRIVATE: 'private' } }));
jest.mock('~/api/permission', () => ({}));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: null }) }));
jest.mock('~/hooks/useSelectCopy', () => ({ __esModule: true, default: () => ({}) }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockNotify }) }));
jest.mock('~/utils', () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(' '),
  getFullWidthLength: (value: string) => value.length,
  truncateByFullWidth: (value: string) => value,
}));
jest.mock('~/components/permission/PermissionDraftPanel', () => ({ PermissionDraftPanel: () => null }));
jest.mock('~/components/permission/PermissionDraftPickerDialog', () => ({ PermissionDraftPickerDialog: () => null }));
jest.mock('./KnowledgeSpaceAccessMode', () => ({ KnowledgeSpaceAccessMode: () => null }));

beforeAll(async () => {
  await i18next.init({ lng: 'en', resources: { en: { translation: { api_errors: messages } } } });
});
beforeEach(() => {
  window.showToast = mockNotify;
  mockSubmit.mockReset();
  mockSettings.mode = 'edit';
});

const save = () => fireEvent.click(screen.getByRole('button', { name: 'com_unified_permission.save' }));
const failure = () => normalizeApiError({ status_code: 10989, status_message: 'Invalid library', data: { message: 'PRIVATE details' } }, { message: 'PRIVATE details' });

it('shows the tag-library business error and retains the edit page for retry', async () => {
  mockSubmit.mockRejectedValueOnce(failure()).mockResolvedValueOnce({ id: '4322' });
  render(<KnowledgeSpaceSettingsPage />);
  save();
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: messages['10989'] })));
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(screen.getByDisplayValue('Keep these edits')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'com_unified_permission.save' })).not.toBeDisabled();
  save();
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: 'com_knowledge.space_updated' })));
  expect(mockNavigate).toHaveBeenCalledTimes(1);
});

it('also shows business errors when creating a space', async () => {
  mockSettings.mode = 'create';
  mockSubmit.mockRejectedValueOnce(failure());
  render(<KnowledgeSpaceSettingsPage />);
  fireEvent.click(screen.getByRole('button', { name: 'com_unified_permission.confirm_create' }));
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: messages['10989'] })));
  expect(mockNavigate).not.toHaveBeenCalled();
});

it.each(['toast', 'global', 'canceled'] as const)('does not duplicate a %s failure notice', async presentation => {
  const error = presentation === 'canceled' ? normalizeApiError({ code: 'ERR_CANCELED' }, { message: 'Canceled' }) : failure();
  if (presentation !== 'canceled') error.presentation = presentation;
  mockSubmit.mockRejectedValueOnce(error);
  render(<KnowledgeSpaceSettingsPage />);
  save();
  await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(1));
  expect(mockNotify).not.toHaveBeenCalled();
  expect(mockNavigate).not.toHaveBeenCalled();
});

it('shows the safe fallback for an unregistered error', async () => {
  mockSubmit.mockRejectedValueOnce(normalizeApiError({ status_code: 49999, status_message: 'PRIVATE' }, { message: 'PRIVATE' }));
  render(<KnowledgeSpaceSettingsPage />);
  save();
  await waitFor(() => expect(mockNotify).toHaveBeenCalledWith(expect.objectContaining({ message: messages.fallback })));
  expect(mockNavigate).not.toHaveBeenCalled();
});
