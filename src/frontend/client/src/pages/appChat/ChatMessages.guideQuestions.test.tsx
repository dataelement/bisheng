import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import ChatMessages from './ChatMessages';
import { emitAreaTextEvent } from './useAreaText';

let mockRunning = { guideWord: ['Example question'], error: { code: '', data: null }, inputDisabled: false, inputForm: false as boolean | object };
jest.mock('recoil', () => ({ useRecoilValue: (key: string) => key === 'running' ? mockRunning : key === 'chat' ? { flow: { flow_type: 5 } } : {} }));
jest.mock('./store/atoms', () => ({ currentRunningState: 'running', currentChatState: 'chat', bishengConfState: 'config' }));
jest.mock('~/store', () => ({ __esModule: true, default: { LaTeXParsing: 'latex' } }));
jest.mock('./useMessages', () => ({ useMessage: () => ({ messages: [], chatId: 'assistant-chat', messageScrollRef: { current: null } }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: {} }) }));
jest.mock('@bisheng/chat', () => ({
  ConversationMessages: () => null,
  SuggestedQuestions: ({ questions, onSelect }: { questions: string[]; onSelect: (value: string) => void }) => <>{questions.map(question => <button key={question} onClick={() => onSelect(question)}>{question}</button>)}</>,
}));
jest.mock('@bisheng/chat/core', () => ({ messagesForPresentation: () => [], createRunLabels: () => ({}) }));
jest.mock('~/components/Chat/MessageSelection', () => ({ SelectionMessagesProvider: ({ children }: React.PropsWithChildren) => <>{children}</>, SelectAllBelowBanner: () => null, MessageCheckbox: () => null }));
jest.mock('~/components/ui/Avatar', () => ({ Avatar: () => null, AvatarImage: () => null, AvatarName: () => null }));
jest.mock('./components/ClientChatMarkdown', () => ({ ClientChatMarkdown: () => null }));
jest.mock('./components/ClientMessageFooter', () => ({ ClientMessageFooter: () => null }));
jest.mock('./components/ClientMessageAttachments', () => ({ ClientMessageAttachments: () => null }));
jest.mock('./components/ClientUserActions', () => ({ ClientUserActions: () => null }));
jest.mock('./components/InputForm', () => ({ __esModule: true, default: () => <div>Workflow form</div> }));
jest.mock('./components/InputFormSkill', () => ({ __esModule: true, default: () => <div>Skill form</div> }));
jest.mock('./useAreaText', () => ({ emitAreaTextEvent: jest.fn(), EVENT_TYPE: { INPUT_SUBMIT: 'input_submit' } }));

beforeEach(() => {
  mockRunning = { guideWord: ['Example question'], error: { code: '', data: null }, inputDisabled: false, inputForm: false };
  jest.clearAllMocks();
});

function open(readOnly = false) {
  return render(<ChatMessages title="Assistant" logo={null} readOnly={readOnly} />);
}

it('shows guide questions with the normal empty error object and submits the selected question', () => {
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Example question' }));
  expect(emitAreaTextEvent).toHaveBeenCalledWith({ action: 'input_submit', data: 'Example question' });
});

it.each(['error', 'disabled', 'form', 'readOnly'])('hides guide questions while %s', reason => {
  if (reason === 'error') mockRunning.error.code = '13010';
  if (reason === 'disabled') mockRunning.inputDisabled = true;
  if (reason === 'form') mockRunning.inputForm = {};
  open(reason === 'readOnly');
  expect(screen.queryByRole('button', { name: 'Example question' })).not.toBeInTheDocument();
});

it('keeps the input form visible when there is no error code', () => {
  mockRunning.inputForm = true;
  open();
  expect(screen.getByText('Skill form')).toBeInTheDocument();
});

it('hides the input form when there is an actual error', () => {
  mockRunning.inputForm = true;
  mockRunning.error.code = '13010';
  open();
  expect(screen.queryByText('Skill form')).not.toBeInTheDocument();
});
