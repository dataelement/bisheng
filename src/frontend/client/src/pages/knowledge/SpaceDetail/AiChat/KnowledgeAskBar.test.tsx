import type { ReactElement, ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { getSpaceTagsApi } from '~/api/knowledge';
import { fireEvent, render as renderUI, screen, waitFor } from '@testing-library/react';
import { KnowledgeAskBar } from './KnowledgeAskBar';
import { parkChatAsk } from '~/components/Chat/chatAskHandoff';

jest.mock('~/api/knowledge', () => ({ getSpaceTagsApi: jest.fn() }));
function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } }, logger: { log: () => {}, warn: console.warn, error: () => {} } });
  return renderUI(ui, { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

const mockNavigate = jest.fn();
const mockNewConversation = jest.fn();
let mockModels = [
  { id: '1', name: 'alpha', displayName: 'Provider / Alpha' },
  { id: '2', name: 'beta', displayName: 'Provider / Beta with a long display name' },
];
jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));
jest.mock('~/components/Chat/chatAskHandoff', () => ({ parkChatAsk: jest.fn() }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useNewConvo: () => ({ newConversation: mockNewConversation }),
  usePrefersMobileLayout: () => false,
  useScrollRevealRef: () => () => {},
}));
jest.mock('~/hooks/queries/endpoints/queries', () => ({ useGetBsConfig: () => ({ data: { models: mockModels } }) }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetWorkbenchModelsQuery: () => ({ data: {} }) }));
jest.mock('~/components/Voice/SpeechToText', () => () => null);
jest.mock('~/components/svg', () => ({ SendIcon: () => null }));
jest.mock('~/utils', () => ({ cn: (...classes: string[]) => classes.filter(Boolean).join(' ') }));

beforeEach(() => {
  jest.mocked(getSpaceTagsApi).mockReset().mockResolvedValue([{ id: 7, name: "Report" }]);
  mockModels = [
    { id: '1', name: 'alpha', displayName: 'Provider / Alpha' },
    { id: '2', name: 'beta', displayName: 'Provider / Beta with a long display name' },
  ];
});

test('picking a model updates the trigger and hands its ID to the fresh conversation', async () => {
  render(<KnowledgeAskBar spaceId="space-1" spaceName="Knowledge" modelValue={1} />);
  fireEvent.click(screen.getByRole('combobox', { name: 'com_ui_select_model' }));
  fireEvent.click(await screen.findByRole('treeitem', { name: /modelPicker.unknownProvider/ }));
  fireEvent.click(await screen.findByRole('treeitem', { name: mockModels[1].displayName }));
  expect(screen.getAllByText(mockModels[1].displayName).length).toBeGreaterThan(0);
  fireEvent.change(screen.getByTestId('knowledge-ai-input'), { target: { value: '  Count the entries  ' } });
  fireEvent.click(screen.getByTestId('send-button'));
  expect(parkChatAsk).toHaveBeenCalledWith({ text: 'Count the entries', modelId: 2, space: { id: 'space-1', name: 'Knowledge' } });
  expect(mockNewConversation).toHaveBeenCalledTimes(1);
  expect(mockNavigate).toHaveBeenCalledWith('/c/new');
});

test('catalog arrival repairs an unavailable initial model and sends the displayed model', async () => {
  const models = mockModels;
  mockModels = [];
  const view = render(<KnowledgeAskBar spaceId="space-1" spaceName="Knowledge" modelValue={99} />);
  expect(screen.getByTestId('knowledge-ai-input')).toBeDisabled();
  mockModels = models;
  view.rerender(<KnowledgeAskBar spaceId="space-1" spaceName="Knowledge" modelValue={99} />);
  await waitFor(() => expect(screen.getByText(models[1].displayName)).toBeInTheDocument());
  fireEvent.change(screen.getByTestId('knowledge-ai-input'), { target: { value: 'Count' } });
  fireEvent.keyDown(screen.getByTestId('knowledge-ai-input'), { key: 'Enter' });
  expect(parkChatAsk).toHaveBeenCalledWith(expect.objectContaining({ modelId: 2 }));
});


test('loads real space tags and transfers the selected tag when asking', async () => {
  render(<KnowledgeAskBar spaceId="12" spaceName="Knowledge" modelValue={1} />);
  const input = screen.getByTestId('knowledge-ai-input');
  fireEvent.change(input, { target: { value: '#' } });
  fireEvent.click(await screen.findByRole('button', { name: /#\s*Report/ }));
  fireEvent.change(input, { target: { value: 'Count' } });
  fireEvent.click(screen.getByTestId('send-button'));
  expect(getSpaceTagsApi).toHaveBeenCalledWith('12');
  expect(parkChatAsk).toHaveBeenCalledWith(expect.objectContaining({ space: { id: '12', name: 'Knowledge', tag: { id: 7, name: 'Report' } } }));
});

test('shows loading instead of an empty tag list while the request is pending', async () => {
  jest.mocked(getSpaceTagsApi).mockReturnValue(new Promise(() => {}));
  render(<KnowledgeAskBar spaceId="12" spaceName="Knowledge" modelValue={1} />);
  fireEvent.change(screen.getByTestId('knowledge-ai-input'), { target: { value: '#' } });
  expect(await screen.findByText('com_ui_loading')).toBeInTheDocument();
  expect(screen.queryByText('com_knowledge.no_matched_tags')).not.toBeInTheDocument();
});

test('shows tag request failure and lets the user retry', async () => {
  jest.mocked(getSpaceTagsApi).mockRejectedValueOnce(new Error('network'));
  render(<KnowledgeAskBar spaceId="12" spaceName="Knowledge" modelValue={1} />);
  fireEvent.change(screen.getByTestId('knowledge-ai-input'), { target: { value: '#' } });
  expect(await screen.findByRole('alert')).toHaveTextContent('com_knowledge.load_tags_failed');
  jest.mocked(getSpaceTagsApi).mockResolvedValue([{ id: 7, name: 'Report' }]);
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
  expect(await screen.findByRole('button', { name: /#\s*Report/ })).toBeInTheDocument();
});
