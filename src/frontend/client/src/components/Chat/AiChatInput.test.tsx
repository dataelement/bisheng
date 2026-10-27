import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
const mockToast = jest.fn();
let mockImageSequence = 0;
let mockUseRealUploader = false;
const mockUpload = jest.fn();
const mockSkills = [{ name: 'research' }];
let mockAvailableSkills = mockSkills;
jest.mock('~/store', () => ({ __esModule: true, default: { selectedAgentTools: 'tools' } }));
jest.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: mockAvailableSkills }) }));
jest.mock('~/api/linsight', () => ({ getSelectableSkills: jest.fn(), checkFileParseStatus: jest.fn() }));
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn() }));
jest.mock('recoil', () => ({
  useRecoilValue: () => ({}),
  useRecoilState: (atom) => {
    const React = jest.requireActual('react');
    const [skills, setSkills] = React.useState(atom === 'skills' ? mockSkills : []);
    const update = React.useCallback((value) => { if (atom === 'skills') mockSetSkills(value); setSkills(value); }, [atom]);
    return [skills, update];
  },
}));
jest.mock('~/store/linsight', () => ({ taskModeSkillsState: () => 'skills' }));
jest.mock('~/pages/appChat/store/atoms', () => ({ bishengConfState: 'config' }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetWorkbenchModelsQuery: () => ({ data: {} }) }));
jest.mock('~/hooks', () => ({ useContainerCompact: () => ({ ref: null, compact: false }) }));
jest.mock('~/hooks/useLocalize', () => () => (key: string) => key);
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock('~/pages/knowledge/knowledgeUtils', () => ({
  resolveUploadSizeLimits: () => ({}), getMaxFileSizeBytesForFile: () => 50 * 1024 * 1024,
  isMediaFileName: () => false, isHiddenPath: () => false,
}));
jest.mock('~/api/apps', () => ({ uploadChatFile: (...args) => mockUpload(...args) }));
jest.mock('~/components/Chat/attachments/MediaAttachmentChip', () => ({ MediaAttachmentChip: () => null }));
jest.mock('~/components/Chat/attachments/UploadAttachmentThumbnail', () => ({ FileUploadThumbnail: () => null }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' '), checkIfScrollable: () => false, generateUUID: () => String(++mockImageSequence) }));
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
  const StubInputFiles = React.forwardRef(({ onChange, accepts }, ref) => {
    React.useImperativeHandle(ref, () => ({
      openPicker: () => onChange([{ name: 'notes.txt', filepath: '/notes.txt' }]), clear: () => {},
      upload: (files: FileList | File[]) => {
        const { isFileNameAccepted } = jest.requireActual('~/common/chatAccept');
        onChange(Array.from(files).filter((file: File) => isFileNameAccepted(file.name, accepts))
          .map((file: File) => ({ name: file.name, filepath: `/uploads/${file.name}` })));
      },
    }));
    return null;
  });
  return React.forwardRef((props, ref) => {
    const Component = mockUseRealUploader
      ? jest.requireActual('~/pages/appChat/components/InputFiles').default
      : StubInputFiles;
    return <Component {...props} ref={ref} />;
  });
});

const config = { tools: [{ id: 'web' }], fileUpload: { enabled: true }, skillEntry: { enabled: true } };
const knowledge = [{ id: 'space-1', name: 'Reference', type: 'space' }];
function props() {
  return {
    bsConfig: config, selectedOrgKbs: knowledge, onSelectedOrgKbsChange: jest.fn(),
    features: { taskModeEntry: true, taskMode: true }, modelOptions: [{ id: 'model' }],
    onSend: jest.fn(), onStop: jest.fn(), onScrollToBottom: jest.fn(), onToggleTaskMode: jest.fn(),
  };
}
beforeEach(() => { mockSetSkills.mockClear(); mockAvailableSkills = mockSkills; mockUseRealUploader = false; });

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


test('selecting a skill in ordinary chat activates task mode and keeps the selected skill', () => {
  const input = props();
  const onToggleTaskMode = jest.fn();
  render(<AiChatInput {...input} features={{ taskModeEntry: true, taskMode: false }} onToggleTaskMode={onToggleTaskMode} />);
  fireEvent.click(screen.getByRole('button', { name: 'skills' }));
  expect(mockSetSkills).toHaveBeenCalledWith(mockSkills);
  expect(onToggleTaskMode).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('/research')).toBeNull();
  expect(screen.getByRole('button', { name: 'research' })).toBeInTheDocument();
});

test('returning to ordinary chat clears selected task skills', () => {
  const input = props();
  const view = render(<AiChatInput {...input} />);
  expect(screen.getByText('/research')).toBeInTheDocument();
  view.rerender(<AiChatInput {...input} features={{ taskModeEntry: true, taskMode: false }} />);
  expect(mockSetSkills).toHaveBeenCalledWith([]);
  expect(screen.queryByText('/research')).toBeNull();
  expect(screen.getByRole('button', { name: 'skills' })).toBeInTheDocument();
});


test.each([true, false])('send acceptance %s controls the entire skill draft reset', (accepted) => {
  const input = props();
  input.onSend.mockReturnValue(accepted);
  render(<AiChatInput {...input} />);
  fireEvent.click(screen.getByRole('button', { name: 'upload' }));
  const editor = screen.getByRole('textbox');
  editor.append(document.createTextNode('Prepare a report'));
  fireEvent.input(editor);
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(input.onSend).toHaveBeenCalledWith('Prepare a report', [{ name: 'notes.txt', filepath: '/notes.txt' }]);
  if (accepted) {
    expect(mockSetSkills).toHaveBeenCalledWith([]);
    expect(mockSetSkills.mock.invocationCallOrder[0]).toBeGreaterThan(input.onSend.mock.invocationCallOrder[0]);
    expect(editor).not.toHaveTextContent('Prepare a report');
    expect(editor).not.toHaveTextContent('/research');
    expect(screen.queryByText('notes.txt')).toBeNull();
  } else {
    expect(mockSetSkills).not.toHaveBeenCalled();
    expect(editor).toHaveTextContent('/research');
    expect(editor).toHaveTextContent('Prepare a report');
    expect(screen.getByTestId('attachments')).toHaveTextContent('notes.txt');
  }
});


test('task mode skill selection keeps the mode active', () => {
  const onToggleTaskMode = jest.fn();
  render(<AiChatInput {...props()} onToggleTaskMode={onToggleTaskMode} />);
  fireEvent.click(screen.getByRole('button', { name: 'skills' }));
  expect(mockSetSkills).toHaveBeenCalledWith(mockSkills);
  expect(onToggleTaskMode).not.toHaveBeenCalled();
});

test('ordinary chat exposes skill selection to users with task mode access', () => {
  const input = props();
  const onToggleTaskMode = jest.fn();
  const view = render(<AiChatInput {...input} features={{ taskModeEntry: false, taskMode: false }} onToggleTaskMode={onToggleTaskMode} />);
  expect(screen.queryByRole('button', { name: 'skills' })).toBeNull();
  view.rerender(<AiChatInput {...input} features={{ taskModeEntry: true, taskMode: false }} onToggleTaskMode={onToggleTaskMode} />);
  expect(screen.getByRole('button', { name: 'skills' })).toBeInTheDocument();
});


test('account availability removes a selected skill while the picker stays closed', () => {
  const input = props();
  const view = render(<AiChatInput {...input} />);
  expect(screen.getByText('/research')).toBeInTheDocument();
  mockAvailableSkills = [];
  view.rerender(<AiChatInput {...input} allowConfiguration={false} />);
  expect(mockSetSkills).toHaveBeenCalledWith([]);
  expect(screen.queryByText('/research')).toBeNull();
});

function pasteImage() {
  const file = new File(['test image'], 'image.png', { type: 'image/png' });
  fireEvent.paste(screen.getByRole('textbox'), {
    clipboardData: { items: [{ kind: 'file', getAsFile: () => file }], getData: () => '' },
  });
}

function enterImageQuestion() {
  screen.getByRole('textbox').append(document.createTextNode('Describe this image'));
  fireEvent.input(screen.getByRole('textbox'));
}

test.each([true, false])('pastes an image with visual=%s and image parsing disabled', (visual) => {
  const input = { ...props(), features: { taskMode: false }, modelValue: 'model', modelOptions: [{ id: 'model', visual }] };
  render(<AiChatInput {...input} />);
  pasteImage();
  expect(screen.getByTestId('attachments')).toHaveTextContent(/image-.*\.png/);
  expect(input.onSend).not.toHaveBeenCalled();
});

test('keeps image and text on an unsupported send, then sends after selecting a vision model', () => {
  const input = { ...props(), features: { taskMode: false }, modelValue: 'text', modelOptions: [{ id: 'text', visual: false }, { id: 'vision', visual: true }] };
  const view = render(<AiChatInput {...input} />);
  pasteImage();
  enterImageQuestion();
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(input.onSend).not.toHaveBeenCalled();
  expect(mockToast).toHaveBeenCalledWith({ message: 'chatImage.processingRequired', status: 'warning' });
  expect(screen.getByTestId('attachments')).toHaveTextContent(/image-.*\.png/);
  expect(screen.getByRole('textbox')).toHaveTextContent('Describe this image');
  view.rerender(<AiChatInput {...input} modelValue="vision" />);
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(input.onSend).toHaveBeenCalledWith('Describe this image', [expect.objectContaining({ filepath: expect.stringMatching(/image-.*\.png/) })]);
});

test('sends through image parsing with a text model', () => {
  const input = { ...props(), bsConfig: { ...config, enable_etl4lm: true }, features: { taskMode: false }, modelValue: 'model' };
  render(<AiChatInput {...input} />);
  pasteImage();
  enterImageQuestion();
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(input.onSend).toHaveBeenCalledTimes(1);
});

test('retains pasted images when leaving task mode', () => {
  const input = props();
  const view = render(<AiChatInput {...input} />);
  pasteImage();
  view.rerender(<AiChatInput {...input} features={{ taskMode: false }} />);
  expect(screen.getByTestId('attachments')).toHaveTextContent(/image-.*\.png/);
});

test('clipboard image passes the real uploader and reaches the send payload without ETL', async () => {
  mockUseRealUploader = true;
  URL.createObjectURL = jest.fn(() => 'blob:clipboard-preview');
  URL.revokeObjectURL = jest.fn();
  mockUpload.mockResolvedValue({ status_code: 200, data: { filepath: '/uploads/pasted-image.png', file_id: 'uploaded-image' } });
  const input = { ...props(), features: { taskMode: false }, modelValue: 'vision', modelOptions: [{ id: 'vision', visual: true }] };
  render(<AiChatInput {...input} />);
  pasteImage();
  await waitFor(() => expect(mockUpload).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByTestId('attachments')).toHaveTextContent(/image-.*\.png/));
  enterImageQuestion();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(input.onSend).toHaveBeenCalledWith('Describe this image', [expect.objectContaining({
    filepath: '/uploads/pasted-image.png', file_id: 'uploaded-image', type: 'image/png',
  })]);
  expect(mockToast).not.toHaveBeenCalled();
});
