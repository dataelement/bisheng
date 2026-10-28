import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { KnowledgeAskBar } from './KnowledgeAskBar';
import { parkChatAsk } from '~/components/Chat/chatAskHandoff';

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
  useScrollRevealRef: () => null,
}));
jest.mock('~/hooks/queries/endpoints/queries', () => ({ useGetBsConfig: () => ({ data: { models: mockModels } }) }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetWorkbenchModelsQuery: () => ({ data: {} }) }));
jest.mock('~/components/Voice/SpeechToText', () => () => null);
jest.mock('~/components/svg', () => ({ SendIcon: () => null }));
jest.mock('~/utils', () => ({ cn: (...classes: string[]) => classes.filter(Boolean).join(' ') }));

beforeEach(() => {
  mockModels = [
    { id: '1', name: 'alpha', displayName: 'Provider / Alpha' },
    { id: '2', name: 'beta', displayName: 'Provider / Beta with a long display name' },
  ];
});

test('picking a model updates the trigger and hands its ID to the fresh conversation', async () => {
  render(<KnowledgeAskBar spaceId="space-1" spaceName="Knowledge" modelValue={1} />);
  fireEvent.click(screen.getByRole('button', { name: 'Provider / Alpha' }));
  fireEvent.click(await screen.findByRole('option', { name: mockModels[1].displayName }));
  const trigger = screen.getByRole('button', { name: mockModels[1].displayName });
  expect(trigger).toHaveAttribute('title', mockModels[1].displayName);
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
  await waitFor(() => expect(screen.getByRole('button', { name: models[1].displayName })).toBeEnabled());
  fireEvent.change(screen.getByTestId('knowledge-ai-input'), { target: { value: 'Count' } });
  fireEvent.keyDown(screen.getByTestId('knowledge-ai-input'), { key: 'Enter' });
  expect(parkChatAsk).toHaveBeenCalledWith(expect.objectContaining({ modelId: 2 }));
});
