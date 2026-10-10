import request from "@/controllers/request";

export type DebugContext = {
  assistant_id: string;
  assistant_name: string;
  configured_model_id: string;
  bot_id: string;
  test_user_id: number;
  test_user_name: string;
  external_identity_available: boolean;
  space_ids: number[];
  spaces: { id: number; name: string }[];
  scope_version: number;
  execution_mode?: string;
  model_name?: string;
  disabled_tools?: string[];
  test_tools?: string[];
};

export type DebugHistoryTurn = { question: string; answer: string };
export type DebugToolCall = {
  call_id: string;
  tool_name: string;
  tool_type: string;
  observer_type: string;
  query: string;
};
type EventPayloads = {
  context: DebugContext;
  tool_start: DebugToolCall;
  tool_end: DebugToolCall & { model_tool_output: string; retrieval_metadata?: Record<string, unknown>[] };
  tool_error: { call_id: string; error_type: string };
  answer_delta: { text: string };
  completed: { tool_call_count: number };
  failed: { error_type: string; tool_call_count: number };
};
export type DebugEvent = {
  [K in keyof EventPayloads]: { run_id: string; seq: number; type: K; data: EventPayloads[K] }
}[keyof EventPayloads];

const root = "/robot-debug/api";
const assistantPath = (id: string) => `${root}/assistants/${encodeURIComponent(id)}`;

export async function getRobotDebugStatus(): Promise<boolean> {
  if (import.meta.env.VITE_EPLUS_DEBUG_ENABLED !== "true") return false;
  try {
    const result = await request.get<{ enabled: boolean }, { enabled: boolean }>(`${root}/status`, { silent: true });
    return result.enabled === true;
  } catch {
    // Optional diagnostics must remain hidden when the isolated service is absent.
    return false;
  }
}

export function getRobotDebugContext(assistantId: string, testUserId?: number, signal?: AbortSignal): Promise<DebugContext> {
  return request.get<DebugContext, DebugContext>(`${assistantPath(assistantId)}/context`, {
    params: testUserId ? { test_user_id: testUserId } : undefined, signal,
  });
}

export function createDebugEventDecoder(onEvent: (event: DebugEvent) => void) {
  let buffer = "", runId = "", seq = 0, terminal = false;
  const push = (chunk: string) => {
    buffer = (buffer + chunk).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).replace(/^ /, "")).join("\n");
      if (data) {
        const event = JSON.parse(data) as DebugEvent;
        if (terminal || !event.run_id || (runId && event.run_id !== runId) || event.seq !== seq + 1 || !event.data ||
          !["context", "tool_start", "tool_end", "tool_error", "answer_delta", "completed", "failed"].includes(event.type)) {
          throw new Error("Invalid robot debug event sequence");
        }
        runId = event.run_id;
        seq = event.seq;
        terminal = event.type === "completed" || event.type === "failed";
        onEvent(event);
      }
      boundary = buffer.indexOf("\n\n");
    }
  };
  return {
    push,
    finish: () => {
      if (!terminal || buffer.trim()) throw new Error("Incomplete robot debug stream");
    },
  };
}

export async function runRobotDebug(
  input: { assistantId: string; query: string; testUserId: number; history: DebugHistoryTurn[] },
  onEvent: (event: DebugEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const decoder = createDebugEventDecoder(onEvent);
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  let consumed = 0, parseError: unknown;
  const consume = (text: string) => {
    decoder.push(text.slice(consumed));
    consumed = text.length;
  };
  try {
    // XHR decodes UTF-8 incrementally. Keep the shared auth/error interceptors.
    await request.post<unknown, void>(`${assistantPath(input.assistantId)}/run`, {
      query: input.query, test_user_id: input.testUserId, history: input.history,
    }, {
      signal: controller.signal, responseType: "text", timeout: 200000,
      onDownloadProgress: progress => {
        const xhr = (progress.event as ProgressEvent<XMLHttpRequest> | undefined)?.target;
        if (!(xhr instanceof XMLHttpRequest) || !xhr.getResponseHeader("Content-Type")?.includes("text/event-stream")) return;
        try { consume(xhr.responseText); } catch (error) { parseError = error; abort(); }
      },
      transformResponse: [(text: string) => {
        if (!text.startsWith("data:")) return JSON.parse(text);
        consume(text);
        decoder.finish();
        return { status_code: 200, data: undefined };
      }],
    });
  } catch (error) {
    throw parseError ?? error;
  } finally {
    signal.removeEventListener("abort", abort);
  }
}
