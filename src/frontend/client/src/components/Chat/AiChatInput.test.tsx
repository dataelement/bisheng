import { fireEvent, render, screen } from '@testing-library/react';
import AiChatInput from './AiChatInput';

// jsdom has no layout observer; behavior tests use deterministic geometry.
beforeAll(() => {
    global.ResizeObserver = class {
        observe() {}
        unobserve() {}
        disconnect() {}
    };
});

const mockSetSkills = jest.fn();
const mockSkills = [{ name: 'research' }];
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn() }));
jest.mock('recoil', () => ({ useRecoilValue: () => ({}), useRecoilState: () => [mockSkills, mockSetSkills] }));
jest.mock('~/store/linsight', () => ({ taskModeSkillsState: () => 'skills' }));
jest.mock('~/pages/appChat/store/atoms', () => ({ bishengConfState: 'config' }));
jest.mock('~/components/Linsight/Input/useDefaultCheckedSkills', () => ({ useDefaultCheckedSkills: () => {} }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetWorkbenchModelsQuery: () => ({ data: {} }) }));
jest.mock('~/hooks', () => ({ useContainerCompact: () => ({ ref: null, compact: false }) }));
jest.mock('~/hooks/useLocalize', () => () => (key: string) => key);
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/pages/appChat/useFileDropAndPaste', () => ({ useFileDropAndPaste: () => ({ isDragging: false }) }));
jest.mock('~/pages/knowledge/knowledgeUtils', () => ({ resolveUploadSizeLimits: () => ({}) }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' '), checkIfScrollable: () => false }));
jest.mock('~/components/svg', () => ({ SendIcon: () => null }));
jest.mock('~/components/ui', () => {
  const React = jest.requireActual('react');
  return {
    Button: 'button',
    TextareaAutosize: React.forwardRef(({ onHeightChange, ...props }, ref) => { void onHeightChange; return <textarea ref={ref} {...props} />; }),
  };
});
jest.mock('./Input/ChatSkillSelector', () => ({ ChatSkillSelector: ({ onChange }) => <button onClick={() => onChange(mockSkills)}>skills</button> }));
jest.mock('./Input/AgentToolSelector', () => () => <button>tools</button>);
jest.mock('./Input/ChatFormTools', () => ({ ChatToolDown: () => <button>legacy tools</button> }));
jest.mock('~/components/Linsight/Input/TaskModeToggle', () => ({ TaskModeToggle: () => <button>research</button> }));
jest.mock('./Input/ChatResourceMenu', () => ({
  ChatResourceMenu: ({ showKnowledgeSelection, showFileUpload, onFileUploadClick, showTools, showResearch, children }) => (
    <div>
      {children}{showTools && <button>tools</button>}{showResearch && <button>research</button>}
      {showKnowledgeSelection && <button>spaces</button>}
      {showFileUpload && <button onClick={onFileUploadClick}>upload</button>}
    </div>
  ),
}));
jest.mock('./Input/AttachmentBar', () => ({
  AttachmentBar: ({ files }) => <div data-testid="attachments">{files.map((file) => file.name).join(',')}</div>,
}));
jest.mock('./Input/Files/DragDropOverlay', () => () => null);
jest.mock('~/components/Voice/SpeechToText', () => () => null);
jest.mock('./AiModelSelect', () => () => <button>model</button>);
jest.mock('~/pages/appChat/components/InputFiles', () => {
  const React = jest.requireActual('react');
  return React.forwardRef(({ onChange }, ref) => {
    React.useImperativeHandle(ref, () => ({
      openPicker: () => onChange([{ name: 'notes.txt', filepath: '/notes.txt' }]), clear: () => {},
    }));
    return null;
  });
});

const config = { tools: [{ id: 'web' }], fileUpload: { enabled: true }, skillEntry: { enabled: true } };
const knowledge = [{ id: 'space-1', name: 'Reference', type: 'space' }];
function props() {
  return {
    bsConfig: config, selectedOrgKbs: knowledge, onSelectedOrgKbsChange: jest.fn(),
    features: { taskModeEntry: true, taskMode: true }, modelOptions: [{ id: 'model' }],
    onSend: jest.fn(), onStop: jest.fn(), onScrollToBottom: jest.fn(),
  };
}
beforeEach(() => mockSetSkills.mockClear());

test('new chat offers setup, established chat hides setup while preserving context', () => {
  const input = props();
  const view = render(<AiChatInput {...input} />);
  for (const label of ['skills', 'tools', 'research', 'spaces']) {
    expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
  }
  expect(screen.getByText('@Reference')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'tools' }).closest('.dsh-chat-composer')).toBeTruthy();
  view.rerender(<AiChatInput {...input} allowConfiguration={false} />);
  for (const label of ['tools', 'research']) {
    expect(screen.queryByRole('button', { name: label })).toBeNull();
  }
  expect(screen.getByText('@Reference')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'spaces' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'skills' })).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toHaveAttribute('contenteditable', 'true');
  expect(input.onSelectedOrgKbsChange).not.toHaveBeenCalled();
  expect(mockSetSkills).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'model' })).toBeInTheDocument();
  view.rerender(<AiChatInput {...input} />);
  expect(screen.getByText('@Reference')).toBeInTheDocument();
});

test('follow-up retains attachment upload and sends its text and file', () => {
  const input = props();
  render(<AiChatInput {...input} allowConfiguration={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'upload' }));
  expect(screen.getByTestId('attachments')).toHaveTextContent('notes.txt');
  screen.getByRole('textbox').append(document.createTextNode('Summarize this file'));
  fireEvent.input(screen.getByRole('textbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(input.onSend).toHaveBeenCalledWith('Summarize this file', [{ name: 'notes.txt', filepath: '/notes.txt' }]);
  expect(input.onSelectedOrgKbsChange).not.toHaveBeenCalled();
});

test('running conversation retains stop action', () => {
  const input = props();
  render(<AiChatInput {...input} allowConfiguration={false} isStreaming />);
  fireEvent.click(screen.getByRole('button', { name: 'Stop generating' }));
  expect(input.onStop).toHaveBeenCalledTimes(1);
});

test('media parsing keeps drafting available while blocking send until parsing completes', () => {
  const input = props();
  const view = render(<AiChatInput {...input} isParsingMedia />);
  const textbox = screen.getByRole('textbox');
  expect(textbox).toBeEnabled();
  textbox.append(document.createTextNode('Draft while parsing'));
  fireEvent.input(textbox);
  expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
  expect(input.onSend).not.toHaveBeenCalled();
  view.rerender(<AiChatInput {...input} isParsingMedia={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(input.onSend).toHaveBeenCalledWith('Draft while parsing', null);
});


test('skills remain selectable in ordinary chat with task entry disabled', () => {
  const toggle = jest.fn();
  const input = props();
  render(<AiChatInput {...input} features={{ taskModeEntry: false, taskMode: false }} onToggleTaskMode={toggle} />);
  fireEvent.click(screen.getByRole('button', { name: 'skills' }));
  expect(mockSetSkills).toHaveBeenCalledWith(mockSkills);
  expect(toggle).not.toHaveBeenCalled();
  expect(screen.getByText('/research')).toBeInTheDocument();
});

test('switching execution mode preserves selected skills', () => {
  const input = props();
  const view = render(<AiChatInput {...input} />);
  view.rerender(<AiChatInput {...input} features={{ taskModeEntry: true, taskMode: false }} />);
  expect(mockSetSkills).not.toHaveBeenCalled();
  expect(screen.getByText('/research')).toBeInTheDocument();
});
