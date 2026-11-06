beforeAll(() => { global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }; });
import { useState, type ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatResourceMenu } from './ChatResourceMenu';
import { useAgentToolPreferences } from './AgentToolSelector';
import { ComposerSubmenu } from './ComposerSubmenu';
import type { BsConfig } from '~/types/chat';

const { RecoilRoot } = jest.requireActual('recoil');
const originalResizeObserver = global.ResizeObserver;
beforeAll(() => {
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver;
});
afterAll(() => { global.ResizeObserver = originalResizeObserver; });

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: { id: 'menu-test' } }), useScrollRevealRef: () => () => {} }));
const mockOrgQuery = jest.fn();
const mockOrgRefetch = jest.fn();
let mockOrgError = false;
jest.mock('~/hooks/queries/data-provider', () => ({
  useGetOrgToolPages: (query) => {
    mockOrgQuery(query);
    return {
      data: { pages: [{ data: [{ id: 1, name: 'Enterprise' }, { id: 2, name: 'Policies' }] }] },
      isFetching: false, isError: mockOrgError, hasNextPage: false,
      fetchNextPage: jest.fn(), refetch: mockOrgRefetch,
    };
  },
}));
beforeEach(() => { mockOrgError = false; mockOrgQuery.mockClear(); });
beforeEach(() => localStorage.clear());
jest.mock('~/store', () => {
  const { atom } = jest.requireActual('recoil');
  return { __esModule: true, default: {
    selectedAgentTools: atom({ key: 'menu-tools', default: [] }),
  } };
});
jest.mock('./KnowledgeSpaceDialog', () => ({ KnowledgeSpaceDialog: () => <div role="dialog" /> }));
const tools = [{ id: 1, name: 'Web search', default_checked: true, children: [{ id: 2, tool_key: 'web_search' }] }];

async function openMenu() {
  fireEvent.keyDown(screen.getByRole('button', { name: 'dshChat.addContext' }), { key: 'ArrowDown' });
  await screen.findByRole('menu');
}

async function openTools() {
  fireEvent.click(screen.getByRole('menuitem', { name: 'com_ui_tools' }));
  await screen.findByRole('menuitem', { name: 'dshChat.backToCapabilities' });
}

function backToMenu() {
  fireEvent.click(screen.getByRole('menuitem', { name: 'dshChat.backToCapabilities' }));
}

test('add menu owns tool toggles and retains selection after reopening', async () => {
  const upload = jest.fn(); const research = jest.fn();
  render(<RecoilRoot><ChatResourceMenu value={[]} onChange={jest.fn()} availableTools={tools}
    showTools showResearch researchActive showFileUpload showKnowledgeSelection
    onFileUploadClick={upload} onResearchChange={research} /></RecoilRoot>);
  expect(screen.queryByRole('menuitemcheckbox')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Web search' })).toBeNull();
  await openMenu();
  await openTools();
  const search = screen.getByRole('menuitemcheckbox', { name: 'Web search' });
  expect(search).toHaveAttribute('aria-checked', 'false');
  fireEvent.click(search);
  expect(search).toHaveAttribute('aria-checked', 'true');
  fireEvent.click(search);
  expect(search).toHaveAttribute('aria-checked', 'false');
  fireEvent.keyDown(search, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  expect(screen.queryByRole('button', { name: 'Web search' })).toBeNull();
  await openMenu();
  await openTools();
  expect(screen.getByRole('menuitemcheckbox', { name: 'Web search' })).toHaveAttribute('aria-checked', 'false');
  backToMenu();
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'com_linsight_task_mode' }));
  expect(research).toHaveBeenCalledTimes(1);
  await openMenu();
  fireEvent.click(screen.getByRole('menuitem', { name: 'com_ui_upload_files' }));
  expect(upload).toHaveBeenCalledTimes(1);
});

test('legacy search toggles through its existing callback; established chat keeps resource actions', async () => {
  const change = jest.fn();
  const props = { value: [], onChange: jest.fn(), showKnowledgeSelection: true, showFileUpload: true };
  const view = render(<RecoilRoot><ChatResourceMenu {...props} showWebSearch onWebSearchChange={change} /></RecoilRoot>);
  await openMenu();
  await openTools();
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'com_tools_web_search' }));
  expect(change).toHaveBeenCalledWith(true);
  backToMenu();
  view.rerender(<RecoilRoot><ChatResourceMenu {...props} /></RecoilRoot>);
  expect(screen.queryByRole('menuitemcheckbox')).toBeNull();
  fireEvent.click(screen.getByRole('menuitem', { name: 'dshChat.selectKnowledge' }));
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
});

test('knowledge bases can be selected independently of spaces, without loading the list before opening', async () => {
  const change = jest.fn();
  const user = userEvent.setup();
  function Picker() {
    const [value, setValue] = useState([
      { id: '1', name: 'Space', type: 'space' as const },
      { id: '1', name: 'Enterprise', type: 'org' as const },
    ]);
    return <ChatResourceMenu value={value} showKnowledgeSelection onChange={next => { change(next); setValue(next); }} />;
  }
  render(<RecoilRoot><Picker /></RecoilRoot>);
  await openMenu();
  expect(mockOrgQuery).not.toHaveBeenCalled();
  await user.click(screen.getByRole('menuitem', { name: 'dshChat.selectKnowledgeBases' }));
  expect(mockOrgQuery).toHaveBeenCalledWith(expect.objectContaining({ action: 'visible' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  await user.click(screen.getByRole('checkbox', { name: 'Policies' }));
  expect(change).not.toHaveBeenCalled();
  await user.click(screen.getByRole('checkbox', { name: 'Enterprise' }));
  await user.click(screen.getByRole('button', { name: 'dshChat.confirmKnowledge' }));
  expect(change).toHaveBeenLastCalledWith([
    { id: '1', name: 'Space', type: 'space' }, { id: '2', name: 'Policies', type: 'org' },
  ]);
});

test('knowledge base read failures offer retry instead of an empty list', async () => {
  mockOrgError = true;
  const user = userEvent.setup();
  render(<RecoilRoot><ChatResourceMenu value={[]} onChange={jest.fn()} showKnowledgeSelection /></RecoilRoot>);
  await openMenu();
  await user.click(screen.getByRole('menuitem', { name: 'dshChat.selectKnowledgeBases' }));
  expect(screen.getByRole('alert')).toHaveTextContent('knowledgeBasePicker.loadError');
  await user.click(screen.getByRole('button', { name: 'dshChat.retryKnowledge' }));
  expect(mockOrgRefetch).toHaveBeenCalledTimes(1);
});

test('disabling organization knowledge hides its entry while keeping spaces available', async () => {
  render(<RecoilRoot><ChatResourceMenu value={[]} onChange={jest.fn()} showKnowledgeSelection
    config={{ knowledgeBase: { enabled: false } } as BsConfig} /></RecoilRoot>);
  await openMenu();
  expect(screen.queryByRole('menuitem', { name: 'dshChat.selectKnowledgeBases' })).toBeNull();
  expect(screen.getByRole('menuitem', { name: 'dshChat.selectKnowledge' })).toBeInTheDocument();
});

function SelectedCapabilities() {
  const [search, setSearch] = useState(false);
  const [research, setResearch] = useState(false);
  return <ChatResourceMenu value={[]} onChange={jest.fn()} showWebSearch showResearch
    webSearchActive={search} onWebSearchChange={setSearch}
    researchActive={research} onResearchChange={() => setResearch((active) => !active)} />;
}

test('selected tools stay in the menu while task mode keeps its own control', async () => {
  render(<RecoilRoot><SelectedCapabilities /></RecoilRoot>);
  await openMenu();
  await openTools();
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'com_tools_web_search' }));
  backToMenu();
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'com_linsight_task_mode' }));
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  expect(screen.queryByRole('button', { name: 'com_tools_web_search' })).toBeNull();
  expect(screen.getByRole('button', { name: 'com_linsight_task_mode' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'com_linsight_task_mode' }));
  await openMenu();
  await openTools();
  expect(screen.getByRole('menuitemcheckbox', { name: 'com_tools_web_search' })).toHaveAttribute('aria-checked', 'true');
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'com_tools_web_search' }));
  expect(screen.getByRole('menuitemcheckbox', { name: 'com_tools_web_search' })).toHaveAttribute('aria-checked', 'false');
});

test('panel follows composer width after resizing and positions above attached resources', async () => {
  let width = 720;
  const originalObserver = global.ResizeObserver;
  global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  const bounds = jest.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    return (this.classList.contains('dsh-chat-composer')
      ? { width, height: 180, top: 300, left: 100, bottom: 480, right: 100 + width }
      : { width: 28, height: 28, top: 440, left: 112, bottom: 468, right: 140 }) as DOMRect;
  });
  const view = render(<RecoilRoot><div className="dsh-chat-composer"><ChatResourceMenu
    value={[]} onChange={jest.fn()} showFileUpload /></div></RecoilRoot>);
  try {
    await openMenu();
    expect(screen.getByRole('menu')).toHaveStyle({ width: '720px' });
    width = 480;
    fireEvent(window, new Event('resize'));
    expect(screen.getByRole('menu')).toHaveStyle({ width: '480px' });
  } finally { view.unmount(); bounds.mockRestore(); global.ResizeObserver = originalObserver; }
});

test('selected platform tools keep their checkbox without a toolbar tag', async () => {
  const configured = [{ id: 3, name: 'Calculator', children: [{ id: 4, tool_key: 'calculator' }] }];
  render(<RecoilRoot><ChatResourceMenu value={[]} onChange={jest.fn()} availableTools={configured} showTools /></RecoilRoot>);
  await openMenu();
  await openTools();
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'Calculator' }));
  fireEvent.keyDown(screen.getByRole('menuitemcheckbox', { name: 'Calculator' }), { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  expect(screen.queryByRole('button', { name: 'Calculator' })).toBeNull();
  await openMenu();
  await openTools();
  expect(screen.getByRole('menuitemcheckbox', { name: 'Calculator' })).toHaveAttribute('aria-checked', 'true');
});

test('skills open a dedicated page and closing resets navigation', async () => {
  render(<RecoilRoot><ChatResourceMenu value={[]} onChange={jest.fn()} showFileUpload>
    <ComposerSubmenu label="Skills" icon={<span />}><input aria-label="Search skills" /></ComposerSubmenu>
  </ChatResourceMenu></RecoilRoot>);
  await openMenu();
  fireEvent.click(screen.getByRole('menuitem', { name: 'Skills' }));
  expect(screen.queryByRole('menuitem', { name: 'com_ui_upload_files' })).toBeNull();
  expect(screen.getByRole('textbox', { name: 'Search skills' })).toHaveFocus();
  fireEvent.click(screen.getByRole('menuitem', { name: 'dshChat.backToCapabilities' }));
  expect(screen.getByRole('menuitem', { name: 'com_ui_upload_files' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('menuitem', { name: 'Skills' }));
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  await openMenu();
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.getByRole('menuitem', { name: 'Skills' })).toBeInTheDocument();
});


test('root starts with task mode and keeps skills and tools in separate second-level menus', async () => {
  render(<RecoilRoot><ChatResourceMenu value={[]} onChange={jest.fn()} availableTools={tools}
    showTools showResearch showFileUpload showKnowledgeSelection>
    <ComposerSubmenu label="Skills" icon={<span />}><input aria-label="Search skills" /></ComposerSubmenu>
  </ChatResourceMenu></RecoilRoot>);
  await openMenu();
  expect(screen.getAllByRole('menuitemcheckbox').map(row => row.getAttribute('aria-label'))).toEqual(['com_linsight_task_mode']);
  expect(screen.getByRole('menu').querySelector('[role^="menuitem"]')).toHaveAttribute('aria-label', 'com_linsight_task_mode');
  expect(screen.queryByRole('menuitemcheckbox', { name: 'Web search' })).toBeNull();
  await openTools();
  expect(screen.getByRole('menuitemcheckbox', { name: 'Web search' })).toBeInTheDocument();
  expect(screen.queryByRole('menuitem', { name: 'Skills' })).toBeNull();
  backToMenu();
  fireEvent.click(screen.getByRole('menuitem', { name: 'Skills' }));
  expect(screen.getByRole('textbox', { name: 'Search skills' })).toHaveFocus();
  expect(screen.queryByRole('menuitemcheckbox', { name: 'Web search' })).toBeNull();
});

function PreferencesOwner({ children }: { children: ReactNode }) {
  useAgentToolPreferences(tools);
  return <>{children}</>;
}

test('user tool choices survive page remounts with executable metadata and an explicit off state', async () => {
  localStorage.setItem('bs:menu-test:selectedAgentTools', '[]');
  const props = { value: [], onChange: jest.fn(), availableTools: tools, showTools: true };
  let view = render(<RecoilRoot><PreferencesOwner><ChatResourceMenu {...props} /></PreferencesOwner></RecoilRoot>);
  await openMenu();
  await openTools();
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'Web search' }));
  await waitFor(() => expect(JSON.parse(localStorage.getItem('bs:menu-test:selectedAgentTools')!)[0].children).toEqual([
    { id: 2, tool_key: 'web_search' },
  ]));
  view.unmount();
  view = render(<RecoilRoot><PreferencesOwner><ChatResourceMenu value={[]} onChange={jest.fn()} showFileUpload /></PreferencesOwner></RecoilRoot>);
  await waitFor(() => expect(JSON.parse(localStorage.getItem('bs:menu-test:selectedAgentTools')!)).toHaveLength(1));
  view.unmount();
  view = render(<RecoilRoot><PreferencesOwner><ChatResourceMenu {...props} /></PreferencesOwner></RecoilRoot>);
  await openMenu();
  await openTools();
  expect(screen.getByRole('menuitemcheckbox', { name: 'Web search' })).toHaveAttribute('aria-checked', 'true');
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'Web search' }));
  await waitFor(() => expect(localStorage.getItem('bs:menu-test:selectedAgentTools')).toBe('[]'));
  view.unmount();
  render(<RecoilRoot><PreferencesOwner><ChatResourceMenu {...props} /></PreferencesOwner></RecoilRoot>);
  await openMenu();
  await openTools();
  expect(screen.getByRole('menuitemcheckbox', { name: 'Web search' })).toHaveAttribute('aria-checked', 'false');
});

test('account-disabled search is unavailable to select until the account enables it', async () => {
  const closed = [{ ...tools[0], children: [{ ...tools[0].children[0], enabled: false }] }];
  const props = { value: [], onChange: jest.fn(), showTools: true };
  const view = render(<RecoilRoot><ChatResourceMenu {...props} availableTools={closed} /></RecoilRoot>);
  await openMenu();
  await openTools();
  const row = screen.getByRole('menuitemcheckbox', { name: 'Web search' });
  expect(row).toHaveAttribute('aria-disabled', 'true');
  fireEvent.click(row);
  expect(row).toHaveAttribute('aria-checked', 'false');
  view.rerender(<RecoilRoot><ChatResourceMenu {...props} availableTools={tools} /></RecoilRoot>);
  const enabled = screen.getByRole('menuitemcheckbox', { name: 'Web search' });
  expect(enabled).not.toHaveAttribute('aria-disabled', 'true');
  expect(enabled).toHaveAttribute('aria-checked', 'false');
  fireEvent.click(enabled);
  expect(enabled).toHaveAttribute('aria-checked', 'true');
});

function DefaultPreferences({ availableTools }: { availableTools?: typeof tools }) {
  useAgentToolPreferences(availableTools);
  return <ChatResourceMenu value={[]} onChange={jest.fn()} availableTools={availableTools} showTools />;
}

test('admin defaults apply after loading without overwriting an explicit empty choice', async () => {
  const defaults = [{ ...tools[0], default_checked: true }];
  const view = render(<RecoilRoot><DefaultPreferences /></RecoilRoot>);
  expect(localStorage.getItem('bs:menu-test:selectedAgentTools')).toBeNull();
  view.rerender(<RecoilRoot><DefaultPreferences availableTools={defaults} /></RecoilRoot>);
  await waitFor(() => expect(JSON.parse(localStorage.getItem('bs:menu-test:selectedAgentTools')!)).toHaveLength(1));
  await openMenu();
  await openTools();
  expect(screen.getByRole('menuitemcheckbox', { name: 'Web search' })).toHaveAttribute('aria-checked', 'true');
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'Web search' }));
  await waitFor(() => expect(localStorage.getItem('bs:menu-test:selectedAgentTools')).toBe('[]'));
  view.unmount();
  render(<RecoilRoot><DefaultPreferences availableTools={defaults} /></RecoilRoot>);
  await openMenu();
  await openTools();
  expect(screen.getByRole('menuitemcheckbox', { name: 'Web search' })).toHaveAttribute('aria-checked', 'false');
});

test('saved choices drop children removed from the configured tool group', async () => {
  localStorage.setItem('bs:menu-test:selectedAgentTools', JSON.stringify([
    { ...tools[0], children: [{ id: 2, tool_key: 'web_search' }, { id: 999, tool_key: 'removed' }] },
  ]));
  render(<RecoilRoot><DefaultPreferences availableTools={tools} /></RecoilRoot>);
  await waitFor(() => expect(JSON.parse(localStorage.getItem('bs:menu-test:selectedAgentTools')!)[0].children).toEqual([
    { id: 2, tool_key: 'web_search' },
  ]));
});
