jest.mock('react-dom/server', () => jest.requireActual('react-dom/server.node'));
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
jest.mock('./Input/ChatResourceMenu', () => ({
  ChatResourceMenu: ({ showKnowledgeSelection, showFileUpload, fileUploadDisabled, fileUploadDisabledReason, onFileUploadClick, showTools, showResearch, researchActive, onResearchChange, children }) => (
    <div>
      {children}{showTools && <button>tools</button>}{showResearch && <button aria-pressed={researchActive} onClick={onResearchChange}>research</button>}
      {showKnowledgeSelection && <button>spaces</button>}
      {showFileUpload && <button disabled={fileUploadDisabled} title={fileUploadDisabledReason} onClick={onFileUploadClick}>upload</button>}
    </div>
  ),
}));
jest.mock('./Input/AttachmentBar', () => ({
  AttachmentBar: ({ files }) => <div data-testid="attachments">{files.map((file) => file.name).join(',')}</div>,
}));
jest.mock('./Input/Files/DragDropOverlay', () => () => null);
jest.mock('~/components/Voice/SpeechToText', () => () => null);
jest.mock('./AiModelSelect', () => ({ disabled, disabledReason }) => <button disabled={disabled} title={disabledReason}>model</button>);
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

test('established chat keeps the setup entries and the selected context', () => {
  const input = props();
  const view = render(<AiChatInput {...input} />);
  for (const label of ['skills', 'tools', 'research', 'spaces']) {
    expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
  }
  expect(screen.getByText('Reference')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'tools' }).closest('.dsh-chat-composer')).toBeTruthy();
  view.rerender(<AiChatInput {...input} allowConfiguration={false} />);
  // Tools travel with each request, so a follow-up turn can still add one.
  expect(screen.getByRole('button', { name: 'tools' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'research' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'research' }));
  expect(input.onToggleTaskMode).toHaveBeenCalledTimes(1);
  expect(screen.getByText('Reference')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'spaces' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'skills' })).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toHaveAttribute('contenteditable', 'true');
  expect(input.onSelectedOrgKbsChange).not.toHaveBeenCalled();
  expect(mockSetSkills).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'model' })).toBeInTheDocument();
  view.rerender(<AiChatInput {...input} />);
  expect(screen.getByText('Reference')).toBeInTheDocument();
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


test('selecting a skill in ordinary chat keeps ordinary chat and mounts the skill', () => {
  const input = props();
  const onToggleTaskMode = jest.fn();
  render(<AiChatInput {...input} features={{ taskModeEntry: true, taskMode: false }} onToggleTaskMode={onToggleTaskMode} />);
  fireEvent.click(screen.getByRole('button', { name: 'skills' }));
  expect(mockSetSkills).toHaveBeenCalledWith(mockSkills);
  expect(onToggleTaskMode).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox')).toHaveTextContent('research');
});

test('returning to ordinary chat keeps the selected skills', () => {
  const input = props();
  const view = render(<AiChatInput {...input} />);
  expect(screen.getByRole('textbox')).toHaveTextContent('research');
  view.rerender(<AiChatInput {...input} features={{ taskModeEntry: true, taskMode: false }} />);
  expect(mockSetSkills).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox')).toHaveTextContent('research');
  expect(screen.getByRole('button', { name: 'skills' })).toBeInTheDocument();
});

test('the skill picker does not depend on the task-mode entry', () => {
  const input = props();
  render(<AiChatInput {...input} features={{ taskModeEntry: false, taskMode: false }} onToggleTaskMode={undefined} />);
  expect(screen.getByRole('button', { name: 'skills' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'research' })).toBeNull();
});


test.each([true, false])('send acceptance %s preserves selected skills while resetting accepted message drafts', async (accepted) => {
  const input = props();
  input.onSend.mockReturnValue(accepted);
  render(<AiChatInput {...input} />);
  fireEvent.click(screen.getByRole('button', { name: 'upload' }));
  const editor = screen.getByRole('textbox');
  editor.append(document.createTextNode('Prepare a report'));
  fireEvent.input(editor);
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send message' })); });
  expect(input.onSend).toHaveBeenCalledWith('Prepare a report', [{ name: 'notes.txt', filepath: '/notes.txt' }]);
  if (accepted) {
    expect(mockSetSkills).not.toHaveBeenCalled();
    expect(editor).not.toHaveTextContent('Prepare a report');
    expect(editor).toHaveTextContent('research');
    expect(screen.queryByText('notes.txt')).toBeNull();
    editor.append(document.createTextNode('Continue the report'));
    fireEvent.input(editor);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send message' })); });
    expect(input.onSend).toHaveBeenLastCalledWith('Continue the report', null);
    expect(editor).toHaveTextContent('research');
    expect(mockSetSkills).not.toHaveBeenCalled();
  } else {
    expect(mockSetSkills).not.toHaveBeenCalled();
    expect(editor).toHaveTextContent('research');
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

test('account availability removes a selected skill while the picker stays closed', () => {
  const input = props();
  const view = render(<AiChatInput {...input} />);
  expect(screen.getByRole('textbox')).toHaveTextContent('research');
  mockAvailableSkills = [];
  view.rerender(<AiChatInput {...input} allowConfiguration={false} />);
  expect(mockSetSkills).toHaveBeenCalledWith([]);
  expect(screen.getByRole('textbox')).not.toHaveTextContent('research');
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


test('shows the permission reason next to the composer and preserves a blocked question', () => {
  const input = props();
  input.onSend.mockReturnValue(false);
  render(<AiChatInput {...input} knowledgeAccessMessage="Space access expired. Choose an accessible space."
    value="D6-W" />);
  expect(screen.getByRole('status')).toHaveTextContent('Space access expired');
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  expect(input.onSend).toHaveBeenCalled();
  expect(screen.getByRole('textbox')).toHaveTextContent('D6-W');
});


test('an accepted send in an abandoned draft keeps the new composer text and files', async () => {
  let finish: (accepted: boolean) => void = () => undefined;
  const onSend = jest.fn(() => new Promise<boolean>(resolve => { finish = resolve; }));
  const input = { ...props(), onSend, features: { taskMode: false } };
  const view = render(<AiChatInput {...input} composerIdentity="project-a-draft" value="Question A" />);
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(onSend).toHaveBeenCalledTimes(1);
  view.rerender(<AiChatInput {...input} composerIdentity="project-b-draft" value="Question B" />);
  fireEvent.click(screen.getByRole('button', { name: 'upload' }));
  expect(screen.getByTestId('attachments')).toHaveTextContent('notes.txt');
  await act(async () => { finish(true); });
  expect(screen.getByRole('textbox')).toHaveTextContent('Question B');
  expect(screen.getByTestId('attachments')).toHaveTextContent('notes.txt');
});


test('an explicit new composer discards unsent files without a late send clearing its successor', async () => {
  let finish: (accepted: boolean) => void = () => undefined;
  const onChange = jest.fn();
  const onSend = jest.fn(() => new Promise<boolean>(resolve => { finish = resolve; }));
  const input = { ...props(), onSend, onChange, features: { taskMode: false } };
  const view = render(<AiChatInput key="draft-a" {...input} composerIdentity="draft-a" value="Question A" />);
  fireEvent.click(screen.getByRole('button', { name: 'upload' }));
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(onSend).toHaveBeenCalledWith('Question A', [{ name: 'notes.txt', filepath: '/notes.txt' }]);
  view.rerender(<AiChatInput key="draft-b" {...input} composerIdentity="draft-b" value="Question B" />);
  expect(screen.queryByTestId('attachments')).toBeNull();
  await act(async () => { finish(true); });
  expect(onChange).not.toHaveBeenCalledWith('');
  expect(screen.getByRole('textbox')).toHaveTextContent('Question B');
  onSend.mockResolvedValue(true);
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Send message' })); });
  expect(onSend).toHaveBeenLastCalledWith('Question B', null);
});

// ── F004 T048: a run in progress accepts messages on the conversation page ──
test('conversation composer keeps the text box and send button usable next to stop while a run is in progress (AC-12)', () => {
  const input = { ...props(), features: { taskMode: false } };
  render(<AiChatInput {...input} composerIdentity="c1" allowConfiguration={false} isStreaming value="Change step 3" />);
  expect(screen.getByRole('textbox')).toHaveAttribute('contenteditable', 'true');
  expect(screen.getByRole('button', { name: 'Stop generating' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
  expect(input.onSend).toHaveBeenCalledWith('Change step 3', null);
  fireEvent.click(screen.getByRole('button', { name: 'Stop generating' }));
  expect(input.onStop).toHaveBeenCalledTimes(1);
});

// ── F004 design §7 item 7: no upload and no model switch while a run is in progress ──
function dropFile() {
  const file = new File(['notes'], 'late.txt', { type: 'text/plain' });
  fireEvent.drop(window, { dataTransfer: { files: [file], items: [], clearData: () => {} } });
}

test('conversation composer locks upload and the model selector while a run is in progress, and says when they come back', () => {
  const input = { ...props(), features: { taskMode: false } };
  const view = render(<AiChatInput {...input} composerIdentity="c1" allowConfiguration={false} isStreaming value="Change step 3" />);
  expect(screen.getByRole('button', { name: 'upload' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'upload' })).toHaveAttribute('title', 'runComposer.uploadLocked');
  expect(screen.getByRole('button', { name: 'model' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'model' })).toHaveAttribute('title', 'runComposer.modelLocked');
  // Typing and sending are not part of the lock.
  expect(screen.getByRole('textbox')).toHaveAttribute('contenteditable', 'true');
  expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled();
  // The run ended: both controls are back, with no leftover reason.
  view.rerender(<AiChatInput {...input} composerIdentity="c1" allowConfiguration={false} value="Change step 3" />);
  expect(screen.getByRole('button', { name: 'upload' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'upload' })).not.toHaveAttribute('title');
  expect(screen.getByRole('button', { name: 'model' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'model' })).not.toHaveAttribute('title');
});

test('conversation composer refuses a pasted or dropped file while a run is in progress and explains why', () => {
  const input = { ...props(), features: { taskMode: false } };
  const view = render(<AiChatInput {...input} composerIdentity="c1" allowConfiguration={false} isStreaming />);
  mockToast.mockClear();
  pasteImage();
  expect(mockToast).toHaveBeenCalledWith({ message: 'runComposer.uploadLocked', status: 'warning' });
  mockToast.mockClear();
  dropFile();
  expect(mockToast).toHaveBeenCalledWith({ message: 'runComposer.uploadLocked', status: 'warning' });
  expect(screen.queryByTestId('attachments')).toBeNull();
  // Once the run ended the same drop is an attachment again.
  view.rerender(<AiChatInput {...input} composerIdentity="c1" allowConfiguration={false} />);
  mockToast.mockClear();
  dropFile();
  expect(mockToast).not.toHaveBeenCalled();
  expect(screen.getByTestId('attachments')).toHaveTextContent('late.txt');
});

test('a streaming run adds no upload or model lock of its own when the input is not the conversation composer', () => {
  const input = { ...props(), features: { taskMode: false } };
  render(<AiChatInput {...input} allowConfiguration={false} isStreaming />);
  expect(screen.getByRole('button', { name: 'upload' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'upload' })).not.toHaveAttribute('title');
  expect(screen.getByRole('button', { name: 'model' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'model' })).not.toHaveAttribute('title');
});

test('conversation composer sends on Enter while a run is in progress (AC-12)', () => {
  const input = { ...props(), features: { taskMode: false } };
  render(<AiChatInput {...input} composerIdentity="c1" allowConfiguration={false} isStreaming value="Go on" />);
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  expect(input.onSend).toHaveBeenCalledWith('Go on', null);
});

test('conversation composer shows no stop button when nothing runs', () => {
  const input = { ...props() };
  render(<AiChatInput {...input} composerIdentity="c1" allowConfiguration={false} />);
  expect(screen.queryByRole('button', { name: 'Stop generating' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Send message' })).toBeInTheDocument();
});

test.each([
  ['the input is not the conversation composer', {}],
  ['the input is the /linsight composer', { composerIdentity: 'c1', isLingsi: true }],
])('a streaming run still blocks the composer when %s', (_name, extra) => {
  const input = { ...props(), features: { taskMode: false }, ...extra };
  render(<AiChatInput {...input} allowConfiguration={false} isStreaming value="Change step 3" />);
  expect(screen.getByRole('textbox')).toHaveAttribute('contenteditable', 'false');
  expect(screen.queryByRole('button', { name: 'Send message' })).toBeNull();
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  expect(input.onSend).not.toHaveBeenCalled();
});
