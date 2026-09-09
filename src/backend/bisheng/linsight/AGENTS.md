# Linsight Agent Subsystem

Auto-loaded when editing files in `src/backend/bisheng/linsight/`. Complements `src/backend/AGENTS.md`.
Subsystem architecture → `docs/architecture/05`. This file holds the contracts and traps that
are not derivable from reading the code — most of them come from the agent framework
(deepagents / langchain / langgraph) behaving differently from what the call site suggests.

---

## Workspace and file handling

- **There is no single "workspace" — there are three stores plus a facade, and the only place they meet is the local `file_dir`.** MinIO `workspace/{svid}/` is the authoritative source for the agent's `ls` / `read_file`; the local cache dir is both a write-through cache and the code executor's cwd; `final_result/{svid}/` is the delivery snapshot (flat, generated names, no subdirectories). Reason about "where did the file go" against that map before reading code.

- **`WorkspaceBackend.grep` is a substring test, not a regex.** `workspace_backend.py` matches with `if pattern in line`, so a model that passes a regex silently gets zero hits — indistinguishable from "no matches". If a tool description invites regex syntax, either implement regex or say plainly that the pattern is literal text.

- **`ls` always reports `is_dir=False`.** Object storage has no directories, so `LsResult` entries are flat. Any middleware that needs real directory semantics (skill enumeration is the recurring case) must be given a separate directory-aware backend rather than reusing the workspace one.

- **Executor artifacts must land in the per-task `file_dir`.** The executor runs as a subprocess on a shared worker, so never harvest container-root paths such as `/output` — steer the model to relative paths through the tool description plus a deterministic self-correction hint, and put that hint on the failing return path (an absolute-path read returns early, so widening a regex further down never fires).

---

## Prompt / tool wiring

- **prompt ⟺ tool lockstep.** For every conditionally available tool (retrieval, code execution, web search), advertising it in the system prompt must be equivalent to actually injecting it. A static prompt keeps urging the model to call a tool that is not bound; the failure surfaces as an argument-validation error rather than "no such tool", which is very hard to attribute. Generate the prompt from the tool list that was actually assembled.

- **A delegated sub-agent's `description` must be self-contained.** The framework replaces the sub-agent's messages with `[HumanMessage(description)]`, so nothing from the main graph's first user message (available knowledge-base ids, scope, phrasing rules) reaches it. Distinguish the two channels: allow-lists and permissions ride along in the tool instance's closure and survive; "what options exist" travels as text and is lost — what you lose is discoverability, not authorization.

- **The only way to put an instruction at the true tail of the system prompt is to append it from a `wrap_model_call` in the last middleware of the list.** Framework-supplied middleware keeps appending its own text after assembly, so the `HarnessProfile` base/suffix slots cannot reach past it. And because the tail is the strongest position, the wording there must be scoped: phrasing like "highest priority, overrides all previous instructions" gets read literally and lets the model discard the workflow and budget constraints above it. State only what the instruction governs, and say explicitly that it changes nothing else.

- **`after_model` middleware runs in reverse list order — last in the list runs first.** Put a corrective middleware at the end of the list if it must fix messages before the others observe them. This is the opposite of the append order in the previous point; do not conflate them.

---

## Model call robustness

- **When the model emits unparseable tool arguments, the graph ends silently instead of retrying.** `create_agent`'s model→tools edge only inspects `tool_calls`; malformed JSON lands in `invalid_tool_calls`, which neither routes to the tools node nor produces a ToolMessage the model could react to, so execution walks straight to END with no final text. Tolerance inside the tool body sits below this edge and can never be reached — intercept in `after_model` and either repair the call or inject an error ToolMessage.

- **Argument tolerance may only degrade and self-heal a bounded number of times; never tighten the schema.** A strict schema rejection makes some models retry until the task is declared finished, which is worse than degrading. The established contract is: one corrective hint, degrade on the second non-conforming attempt. Non-OpenAI models (Qwen / DeepSeek family) additionally stringify nested arguments in three shapes — the whole payload JSON-encoded, string elements inside a list, and an array stuffed into a dict field's value — so recovery must cover all three and fall back to empty rather than raising. The invariant worth asserting in tests is "the user never sees a raw JSON blob", not the number of recoveries.

- **A required-field `Field required` error is usually positive evidence of truncation, not a model that cannot count arguments.** On the streaming path tool-call arguments are parsed with `parse_partial_json`; when the cut falls before the value bytes of a large field (a whole report body, say), the parser backtracks and drops that key, and the remaining dict then fails pydantic validation. Detect `finish_reason in {length, max_tokens}` together with a tool call, inject a "write it in parts" correction, and bound the retries. A hard circuit-breaker must live in `after_model` — raising from `wrap_tool_call` gets swallowed by ToolNode.

- **`tool_call_id` is not guaranteed unique across requests.** The spec only promises that a ToolMessage can reference the id within one response; some gateways return `<tool_name>:<index>` counted from zero each turn. Upserting history by call id then collapses hundreds of calls into a few rows, and — worse — once a ToolMessage is byte-identical at temperature 0, `context(n+1) = f(context(n))` becomes a deterministic fixed point the model cannot leave. Mint display ids at the event-mapper boundary (`<original>#<run_token>:<seq>`; the run token is required because resume and follow-up are each a new instance) and **never** change the id sent back to the provider, since it travels with the message history into the checkpoint. Any fix must also inject something monotonic (an attempt counter) — adding information alone does not break a fixed point.

- **Sub-agent turn budgets are shared across every call.** The framework compiles a sub-agent once when the tool is built and re-enters the same runnable, while the middleware's counter is an instance attribute that is never reset — two parallel sub-agents therefore get half a budget each. Bucket the counter by the runtime `checkpoint_ns` prefix, and force the main graph into a single bucket: its namespace changes every turn, so bucketing there would reset the budget continuously.

- **`recursion_limit` is a fuse, not the business gate.** The turn budget is the gate; the fuse must trip strictly later, otherwise the graceful-degradation ladder never runs and the task falls into partial salvage. Note that no-op tool calls (writing a todo, say) still burn a full turn — any refund mechanism needs a ceiling, or a tight loop keeps the ladder from ever firing.

- **Classify LLM errors in two layers, and keep vendor codes out of the first.** The layer that drives retry behaviour looks only at HTTP status and exception type (RETRYABLE / FAIL_FAST / DEGRADABLE); vendor signatures belong to the layer that picks user-facing copy, where a miss just falls back to generic text. Two invariants: quota must be decided before rate limiting, or a genuinely exhausted account is retried forever; and the same vendor code can mean opposite things on a native endpoint and on an OpenAI-compatible gateway, which no amount of inspection can disambiguate. Do not wrap the model in `.with_retry()` — it drops `bind_tools` and breaks the tool chain; use the framework's `awrap_model_call` hook.

- **`visual` is the field name for vision capability** (`model_info.visual`, used in `workstation/domain/services/chat_service.py`) — grepping for `vision` or `multimodal` finds nothing. A second, orthogonal axis: some endpoints constrain images by *message role* (images accepted only on user messages; attached to a ToolMessage they 400), independently of which block types are accepted. When relocating image blocks into a synthesized user message, insert it **after** the whole batch of tool messages — splitting the batch violates the requirement that tool messages stay contiguous.

- **HITL tools must be `async def`.** A synchronous `@tool` is dispatched by ToolNode through `ainvoke` onto a thread pool under `astream`; `interrupt()` reads its runtime context from a contextvar, which is lost there, so `GraphInterrupt` never propagates, the task does not park, and the model degrades into printing the clarification question as plain text and finishing.

---

## Diagnostics

- **`Worker node crash detected` only proves the linsight worker's main process started once.** It is written by startup cleanup, which scans `IN_PROGRESS` tasks across tenants without checking ownership — so any worker restart can mark tasks on other nodes as failed. It says nothing about who ran out of memory or about the current task. Discriminator: grep the log for `Terminated N incomplete tasks`; `N > 1` means a batch mis-kill. Related: events are RPUSHed to Redis and consumed with BLPOP, so a high event rate exhausts Redis memory, not worker RSS.

- **The framework's history-summarization middleware is non-mutating.** It only takes effect inside `wrap_model_call`; not one entry is removed from `state["messages"]`. It helps the token budget and does **nothing** for process memory or checkpoint size — checkpoint serialization writes a full snapshot under a new key at every step and the index only grows. Do not read "summarization exists" as "long tasks are handled".

- **`cannot assign to field '__traceback__'` never names the real culprit.** It means a `@dataclass(frozen=True)` exception (MinIO's `S3Error` is the recurring one) hit langgraph's traceback trimming on re-raise, which erases the original. Look for the "During handling of the above exception" section in the log; on the resume path, sites that only log `str(e)` have no stack, so recover it from the execution block's exception branch.

- **Object storage signals "not found" by raising, not by returning `None`.** A graceful `if data is None: return not_found` branch is dead code and a missing key escapes and kills the task. Catch `NoSuchKey` explicitly, normalize it to not-found, and let everything else propagate.

- **Do not take `messages[-1]` when salvaging a partial result.** When a recursion or turn limit interrupts the run, the tail is often a ToolMessage carrying raw JSON; pasting that after an apology preamble leaks it straight to the user. Walk back to the last AIMessage that actually has text, skipping Tool/Human/System, and return empty so the caller can degrade to a clean failure.

- **The code executor's tool description must state which libraries the environment provides.** Without that list the model free-associates (`pdfminer`, `pdfplumber`, `PyPDF2`, …), and its own `except` blocks print the failures into the log where they read like platform errors. Chasing installs never converges — list the available libraries and state that `pip install` is not available.

---

## File type handling

- **The agent framework picks the returned block type from the file extension, which can bypass the backend's "text only" contract.** `.pdf` / `.ppt` / `.pptx` map to a `file` block (`content_blocks=[{"type": "file", "base64": …}]`), and most OpenAI-compatible endpoints accept only `text` / `image_url` / `video_url` — the request 400s and the whole task fails. The quieter variant: a binary extension that is *not* in the mapping table takes the text branch and feeds mojibake to the model without any error. Never leave an unparsed original in the workspace under its binary extension, and add a guard at the model-request layer that strips or downgrades any block type the endpoint does not accept.
