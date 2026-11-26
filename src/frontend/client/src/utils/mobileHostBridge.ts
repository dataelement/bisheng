import type { TaskModeSkill } from "~/store/linsight";
import type { SelectedAgentTool, SelectedOrgKb } from "~/store/modeltype";

/** Draft the phone hands to a page that is already on blank `/c/new`. */
export type PreparedMobileHostSend = {
  text: string;
  files: Array<Record<string, unknown>>;
  taskMode: boolean;
  searchEnabled: boolean;
  model?: { id: number; name: string };
  tools: SelectedAgentTool[];
  knowledge: SelectedOrgKb[];
  skills: TaskModeSkill[];
};

export type MobileHostApi = {
  send: (draft: unknown) => Promise<void>;
  resetBlank: () => void;
};

type MobileHostWindow = Window & {
  __bsMobileHost?: MobileHostApi;
  BishengMobile?: { postMessage?: (value: string) => void };
};

type SendDeps = {
  conversationId?: string | null;
  apply: (prepared: PreparedMobileHostSend) => void;
  sendMessage: (
    text: string,
    files: Array<Record<string, unknown>>,
    opts: {
      taskMode: boolean;
      hostDraft: PreparedMobileHostSend;
      onTurnCreated: (conversationId: string) => void;
    },
  ) => Promise<boolean>;
  post: (message: Record<string, unknown>) => void;
};

function textOf(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function numberOf(value: unknown): number | undefined {
  const parsed = typeof value === "number" ? value : Number(textOf(value));
  return Number.isFinite(parsed) ? parsed : undefined;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(textOf).filter((item) => item.length > 0);
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => {
    return item != null && typeof item === "object" && !Array.isArray(item);
  });
}

/**
 * Turns the phone draft into the values `sendMessage` closes over.
 * Missing or mistyped fields are omitted; they never reject the whole draft.
 */
export function prepareMobileHostSend(draft: unknown): PreparedMobileHostSend {
  const data = draft != null && typeof draft === "object" && !Array.isArray(draft)
    ? draft as Record<string, unknown>
    : {};
  const modelId = numberOf(data.modelId);
  const names = stringList(data.skillNames);
  const skillIds = Array.isArray(data.skillIds) ? data.skillIds : [];
  const skills: TaskModeSkill[] = names.map((name, index) => {
    const id = numberOf(skillIds[index]);
    return { name, display_name: name, ...(id != null && id > 0 ? { id } : {}) };
  });
  const tools: SelectedAgentTool[] = [{
    id: 0,
    name: "",
    children: recordList(data.tools).flatMap((tool) => {
      const id = numberOf(tool.id);
      const toolKey = textOf(tool.tool_key) || textOf(tool.toolKey);
      if (id == null || toolKey.length === 0) return [];
      return [{ id, tool_key: toolKey, name: textOf(tool.name) || undefined }];
    }),
  }].filter((group) => group.children.length > 0);
  const knowledge: SelectedOrgKb[] = [
    ...stringList(data.orgIds).map((id) => ({ id, name: "", type: "org" })),
    ...stringList(data.spaceIds).map((id) => ({ id, name: "", type: "space" })),
  ];
  return {
    text: textOf(data.text),
    files: recordList(data.files),
    taskMode: data.taskMode === true,
    searchEnabled: data.searchEnabled === true,
    ...(modelId != null && modelId > 0 ? { model: { id: modelId, name: "" } } : {}),
    tools,
    knowledge,
    skills,
  };
}

export function postMobileHost(message: Record<string, unknown>): void {
  const channel = (window as MobileHostWindow).BishengMobile;
  if (!channel || typeof channel.postMessage !== "function") return;
  channel.postMessage(JSON.stringify(message));
}

/**
 * Writes the draft into the page, then uses the existing send.
 * `turn-started` is posted only after that send accepts, which is after the
 * optimistic user line and placeholder reply are on screen.
 */
export async function runMobileHostSend(draft: unknown, deps: SendDeps): Promise<void> {
  if (deps.conversationId && deps.conversationId !== "new") {
    deps.post({ type: "send-failed", handedOff: false });
    return;
  }
  const prepared = prepareMobileHostSend(draft);
  deps.apply(prepared);
  try {
    const accepted = await deps.sendMessage(prepared.text, prepared.files, {
      taskMode: prepared.taskMode,
      hostDraft: prepared,
      onTurnCreated: (conversationId) => {
        deps.post({ type: "turn-started", conversationId });
      },
    });
    if (!accepted) {
      deps.post({ type: "send-failed", handedOff: false });
      return;
    }
    deps.post({ type: "turn-started" });
  } catch {
    deps.post({ type: "send-failed", handedOff: true });
  }
}

/** Registers the host API only for the mobile app embed. */
export function publishMobileHost(enabled: boolean, api: MobileHostApi | null): void {
  const host = window as MobileHostWindow;
  if (!enabled || api == null) {
    if (api == null || host.__bsMobileHost === api) delete host.__bsMobileHost;
    return;
  }
  host.__bsMobileHost = api;
}
