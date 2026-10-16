import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChatResourceMenu } from './ChatResourceMenu';

const { RecoilRoot } = jest.requireActual('recoil');

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/store', () => {
  const { atom } = jest.requireActual('recoil');
  return { __esModule: true, default: {
    selectedAgentTools: atom({ key: 'menu-tools', default: [] }),
    agentToolsInitialized: atom({ key: 'menu-initialized', default: false }),
  } };
});
jest.mock('./KnowledgeSpaceDialog', () => ({ KnowledgeSpaceDialog: () => <div role="dialog" /> }));
const tools = [{ id: 1, name: 'Web search', default_checked: true, children: [{ id: 2, tool_key: 'web_search' }] }];

async function openMenu() {
  fireEvent.keyDown(screen.getByRole('button', { name: 'dshChat.addContext' }), { key: 'ArrowDown' });
  await screen.findByRole('menu');
}

test('add menu owns tool toggles and retains selection after reopening', async () => {
  const upload = jest.fn(); const research = jest.fn();
  render(<RecoilRoot><ChatResourceMenu value={[]} onChange={jest.fn()} availableTools={tools}
    showTools showResearch researchActive showFileUpload showKnowledgeSelection
    onFileUploadClick={upload} onResearchChange={research} /></RecoilRoot>);
  expect(screen.queryByRole('menuitemcheckbox')).toBeNull();
  expect(await screen.findByRole('button', { name: 'Web search' })).toHaveAttribute('aria-pressed', 'true');
  await openMenu();
  const search = screen.getByRole('menuitemcheckbox', { name: 'Web search' });
  expect(search).toHaveAttribute('aria-checked', 'true');
  fireEvent.click(search);
  expect(search).toHaveAttribute('aria-checked', 'false');
  fireEvent.keyDown(search, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  expect(screen.queryByRole('button', { name: 'Web search' })).toBeNull();
  await openMenu();
  expect(screen.getByRole('menuitemcheckbox', { name: 'Web search' })).toHaveAttribute('aria-checked', 'false');
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
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'com_tools_web_search' }));
  expect(change).toHaveBeenCalledWith(true);
  view.rerender(<RecoilRoot><ChatResourceMenu {...props} /></RecoilRoot>);
  expect(screen.queryByRole('menuitemcheckbox')).toBeNull();
  fireEvent.click(screen.getByRole('menuitem', { name: 'dshChat.selectKnowledge' }));
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
});

function SelectedCapabilities() {
  const [search, setSearch] = useState(false);
  const [research, setResearch] = useState(false);
  return <ChatResourceMenu value={[]} onChange={jest.fn()} showWebSearch showResearch
    webSearchActive={search} onWebSearchChange={setSearch}
    researchActive={research} onResearchChange={() => setResearch((active) => !active)} />;
}

test('selected capabilities appear beside add and removing them updates menu checks', async () => {
  render(<RecoilRoot><SelectedCapabilities /></RecoilRoot>);
  expect(screen.queryByRole('button', { name: 'com_tools_web_search' })).toBeNull();
  await openMenu();
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'com_tools_web_search' }));
  fireEvent.click(screen.getByRole('menuitemcheckbox', { name: 'com_linsight_task_mode' }));
  await waitFor(() => expect(screen.queryByRole('menu')).toBeNull());
  fireEvent.click(screen.getByRole('button', { name: 'com_tools_web_search' }));
  expect(screen.queryByRole('button', { name: 'com_tools_web_search' })).toBeNull();
  expect(screen.getByRole('button', { name: 'com_linsight_task_mode' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'com_linsight_task_mode' }));
  await openMenu();
  expect(screen.getByRole('menuitemcheckbox', { name: 'com_tools_web_search' })).toHaveAttribute('aria-checked', 'false');
  expect(screen.getByRole('menuitemcheckbox', { name: 'com_linsight_task_mode' })).toHaveAttribute('aria-checked', 'false');
});
