import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { KnowledgeAskBar } from './KnowledgeAskBar';
import { KnowledgeAiBottomDock } from './KnowledgeAiBottomDock';
import { parkChatAsk } from '~/components/Chat/chatAskHandoff';

const mockNavigate = jest.fn();
const mockNewConversation = jest.fn();
let mockMobile = false;
let mockModels = [
  { id: '1', name: 'alpha', displayName: 'Provider / Alpha' },
  { id: '2', name: 'beta', displayName: 'Provider / Beta with a long display name' },
];
jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));
jest.mock('~/components/Chat/chatAskHandoff', () => ({ parkChatAsk: jest.fn() }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useNewConvo: () => ({ newConversation: mockNewConversation }),
  usePrefersMobileLayout: () => mockMobile,
  useScrollRevealRef: () => null,
}));
jest.mock('recoil', () => ({ useRecoilValue: () => ({ id: 1 }) }));
jest.mock('~/store', () => ({ __esModule: true, default: { chatModel: 'model' } }));
jest.mock('~/hooks/queries/endpoints/queries', () => ({ useGetBsConfig: () => ({ data: { models: mockModels } }) }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetWorkbenchModelsQuery: () => ({ data: {} }) }));
jest.mock('~/components/Voice/SpeechToText', () => () => null);
jest.mock('~/components/svg', () => ({ SendIcon: () => null }));
jest.mock('~/utils', () => ({ cn: (...classes: string[]) => classes.filter(Boolean).join(' ') }));

beforeEach(() => {
  mockMobile = false;
  mockModels = [
    { id: '1', name: 'alpha', displayName: 'Provider / Alpha' },
    { id: '2', name: 'beta', displayName: 'Provider / Beta with a long display name' },
  ];
});

test.each([false, true])('the space dock hands off to the main chat without local history (mobile=%s)', (mobile) => {
  mockMobile = mobile;
  render(<KnowledgeAiBottomDock spaceId="space-1" spaceName="Knowledge" />);
  expect(screen.queryByRole('button', { name: 'com_knowledge.history_chat' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'com_knowledge.create_chat' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'com_ui_expand' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText('com_knowledge.ask_bar_placeholder'), { target: { value: '  Question  ' } });
  fireEvent.click(screen.getByTestId('send-button'));
  expect(parkChatAsk).toHaveBeenCalledWith({ text: 'Question', modelId: 1, space: { id: 'space-1', name: 'Knowledge' } });
  expect(mockNewConversation).toHaveBeenCalledTimes(1);
  expect(mockNavigate).toHaveBeenCalledWith('/c/new');
});

test('picking a model updates the trigger and hands its ID to the fresh conversation', async () => {
  render(<KnowledgeAskBar spaceId="space-1" spaceName="Knowledge" modelValue={1} />);
  fireEvent.click(screen.getByRole('combobox', { name: 'com_ui_select_model' }));
  fireEvent.click(await screen.findByRole('treeitem', { name: 'modelPicker.unknownProvider' }));
  fireEvent.click(await screen.findByRole('treeitem', { name: mockModels[1].displayName }));
  const trigger = screen.getByRole('combobox', { name: 'com_ui_select_model' });
  expect(trigger.parentElement).toHaveTextContent(mockModels[1].displayName);
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
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'com_ui_select_model' }).parentElement).toHaveTextContent(models[1].displayName));
  fireEvent.change(screen.getByTestId('knowledge-ai-input'), { target: { value: 'Count' } });
  fireEvent.keyDown(screen.getByTestId('knowledge-ai-input'), { key: 'Enter' });
  expect(parkChatAsk).toHaveBeenCalledWith(expect.objectContaining({ modelId: 2 }));
});
