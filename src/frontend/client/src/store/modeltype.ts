import { atom } from 'recoil';

export type SelectedOrgKb = {
  id: string;
  name: string;
  type: string;
};

// v2.5 Agent-mode: the subset of WorkstationConfig.tools the user has toggled on.
// Parent-level selection — one entry per parent group. Children (leaves) are
// flattened at request time so the backend still receives per-tool payloads.
export type SelectedAgentToolChild = {
  id: number;
  tool_key: string;
  name?: string;
  desc?: string;
};

export type SelectedAgentTool = {
  id: number;
  name: string;
  description?: string;
  children: SelectedAgentToolChild[];
};

const searchType = atom<string>({
  key: 'searchType',
  default: '',
});

const isSearch = atom<boolean>({
  key: 'isSearch',
  default: false,
});

// The model currently shown by the MAIN chat (/c). It is derived state: the
// value is resolved per conversation and mode by `useChatModelResolution`,
// which owns the storage (`bs:{uid}:convModel:{mode}:{convId}` for the
// conversation, `bs:{uid}:chatModel` / `bs:{uid}:taskModel` for the user-level
// default a NEW conversation inherits). Everything under `bs:*` is cleared on
// re-login. `manual: true` marks a value that came from a deliberate selection
// rather than an applied default; `mode` records which mode it belongs to so
// the two memories stay separate.
//
// The satellite surfaces (knowledge-space Q&A, article / file docks) do NOT
// write this atom — they keep their own selection via `useSurfaceModel`, so
// switching models there no longer changes what the main chat shows.
const chatModel = atom<{ id: number; name: string; manual?: boolean; mode?: 'daily' | 'task' }>({
  key: 'chatModel',
  default: { id: 0, name: '' },
});

const selectedOrgKbs = atom<SelectedOrgKb[]>({
  key: 'selectedOrgKbs',
  default: []
});

// v2.5: tools currently toggled on in the input bar. Session-scoped (not
// persisted) — each chat session starts from the admin-configured
// default_checked set in ChatView's initialisation effect.
const selectedAgentTools = atom<SelectedAgentTool[]>({
  key: 'selectedAgentTools',
  default: []
});

// Tracks whether selectedAgentTools has been initialised from bsConfig for
// the current session, so we don't repeatedly reset on every bsConfig update.
const agentToolsInitialized = atom<boolean>({
  key: 'agentToolsInitialized',
  default: false
});

const chatId = atom({
  key: 'chatId',
  default: ''
});

const enableOrgKb = atom<boolean>({
  key: 'enableOrgKb',
  default: false
});

const chatStatesMap = atom<Record<string, any>>({
  key: 'chatStatesMap',
  default: {}
});

export default {
  searchType,
  isSearch,
  chatModel,
  selectedOrgKbs,
  selectedAgentTools,
  agentToolsInitialized,
  enableOrgKb,
  chatId,
  chatStatesMap,
};
