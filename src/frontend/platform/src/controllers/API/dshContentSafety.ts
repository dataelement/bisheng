import request from "@/controllers/request";
import { contentSafetyStates } from "@/types/dshContentSafety";
import type {
  ContentSafetyEventMetadata,
  ContentSafetyEventPage,
  DshSafetyCapabilities,
  DshSafetyLimits,
  DshSensitivePolicy,
  DshSensitivePolicyCommand,
  DshSensitivePolicySaved,
} from "@/types/dshContentSafety";

const gateway = "/api/sensitive/dsh";
const audit = "/api/v1/dsh/admin/model-audit";
const malformed = () => new Error("Invalid DSH content safety response");
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const integer = (value: unknown, minimum = 0): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
const uuid = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value);
const digest = (value: unknown): value is string =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const stamp = (value: unknown): value is string =>
  typeof value === "string" &&
  /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|\+00:00)$/.test(value) &&
  Number.isFinite(Date.parse(value));
const nullable = (value: unknown, valid: (item: unknown) => boolean) =>
  value === null || valid(value);
const decimalId = (value: unknown): value is string =>
  typeof value === "string" &&
  /^[1-9][0-9]{0,18}$/.test(value) &&
  (value.length < 19 || value <= "9223372036854775807");
const member = (value: unknown, choices: readonly string[]) =>
  typeof value === "string" && choices.includes(value);
const details = (value: unknown) =>
  member(value, ["AVAILABLE", "PENDING", "PURGED", "UNREPORTED"]);

function validLimits(value: unknown): value is DshSafetyLimits {
  return (
    object(value) &&
    [
      "custom_words_max_bytes",
      "effective_words_max_count",
      "effective_words_max_bytes",
      "word_max_codepoints",
      "request_max_bytes",
      "response_max_bytes",
      "event_max_bytes",
      "rule_refs_max_count",
    ].every((key) => integer(value[key], 1))
  );
}

function parsePolicy(value: unknown): DshSensitivePolicy {
  if (
    !object(value) ||
    !integer(value.version) ||
    typeof value.enabled !== "boolean" ||
    typeof value.input_enabled !== "boolean" ||
    typeof value.output_enabled !== "boolean" ||
    !Array.isArray(value.words_types) ||
    !value.words_types.every((source) => source === "1" || source === "2") ||
    typeof value.custom_words !== "string" ||
    typeof value.auto_reply !== "string" ||
    !digest(value.builtin_digest) ||
    !integer(value.effective_word_count) ||
    !validLimits(value.limits)
  )
    throw malformed();
  return value as DshSensitivePolicy;
}

function managementConfig(tenantId: number, signal?: AbortSignal) {
  if (!integer(tenantId, 1))
    throw new Error("Invalid DSH content safety tenant");
  return {
    params: { tenant_id: tenantId },
    signal,
    preserveError: true,
    headers: { "Cache-Control": "no-store" },
  };
}

export async function getDshSensitivePolicy(
  tenantId: number,
  signal?: AbortSignal,
): Promise<DshSensitivePolicy> {
  return parsePolicy(
    await request.get(
      gateway + "/settings",
      managementConfig(tenantId, signal),
    ),
  );
}

export async function getDshSafetyCapabilities(
  tenantId: number,
  signal?: AbortSignal,
): Promise<DshSafetyCapabilities> {
  const value: unknown = await request.get(
    gateway + "/capabilities",
    managementConfig(tenantId, signal),
  );
  if (
    !object(value) ||
    typeof value.available !== "boolean" ||
    typeof value.enabled !== "boolean" ||
    typeof value.configuration_ready !== "boolean" ||
    !nullable(value.builtin_digest, digest) ||
    !validLimits(value.limits)
  )
    throw malformed();
  return value as DshSafetyCapabilities;
}

export async function saveDshSensitivePolicy(
  tenantId: number,
  command: DshSensitivePolicyCommand,
  signal?: AbortSignal,
): Promise<DshSensitivePolicySaved> {
  // Project only browser-editable fields; tenant and updater identity come from live authorization.
  const body: DshSensitivePolicyCommand = {
    expected_version: command.expected_version,
    enabled: command.enabled,
    input_enabled: command.input_enabled,
    output_enabled: command.output_enabled,
    words_types: command.words_types,
    custom_words: command.custom_words,
    auto_reply: command.auto_reply,
  };
  const value: unknown = await request.put(
    gateway + "/settings",
    body,
    managementConfig(tenantId, signal),
  );
  const policy = parsePolicy(value);
  if (
    !object(value) ||
    !integer(value.effective_within_seconds, 1) ||
    value.effective_within_seconds > 5
  )
    throw malformed();
  return {
    ...policy,
    effective_within_seconds: value.effective_within_seconds,
  };
}

export function isDshSensitivePolicyConflict(error: unknown): boolean {
  if (!object(error) || !object(error.response)) return false;
  return (
    error.response.status === 409 ||
    (object(error.response.data) && error.response.data.status_code === 409)
  );
}

function validConversation(value: unknown): boolean {
  if (value === null) return true;
  if (
    !object(value) ||
    Object.keys(value).some(
      (key) =>
        ![
          "conversation_id",
          "request_kind",
          "session_origin",
          "parent_conversation_id",
        ].includes(key),
    )
  )
    return false;
  return (
    ["conversation_id", "parent_conversation_id"].every(
      (key) =>
        value[key] === undefined ||
        nullable(
          value[key],
          (item) =>
            typeof item === "string" &&
            Array.from(item).length > 0 &&
            Array.from(item).length <= 256,
        ),
    ) &&
    (value.request_kind === undefined ||
      value.request_kind === null ||
      member(value.request_kind, ["chat", "compaction", "session-title"])) &&
    (value.session_origin === undefined ||
      value.session_origin === null ||
      member(value.session_origin, ["main", "subagent"]))
  );
}

function validMatchedWords(value: unknown, stages: unknown): boolean {
  if (value === undefined || value === null) return true;
  if (!object(value) || !object(stages) || Object.keys(value).length !== 2) return false;
  let count = 0;
  for (const direction of ["input", "output"]) {
    const words = value[direction];
    if (!Array.isArray(words) || words.length > 20 || new Set(words).size !== words.length) return false;
    count += words.length;
    if (count > 20 || (words.length && stages[direction] !== "BLOCKED")) return false;
    if (!words.every((word) => typeof word === "string" && word.length <= 512 && word.trim().length > 0 &&
      Array.from(word).length <= 256 && Array.from(word).every((part) => {
        const point = part.codePointAt(0)!;
        return point < 0xd800 || point > 0xdfff;
      }))) return false;
  }
  return true;
}

function validEvent(value: unknown): value is ContentSafetyEventMetadata {
  if (
    !object(value) ||
    ["tenant_id", "payload", "payload_hash", "raw_text", "authorization"].some(
      (key) => key in value,
    ) ||
    value.schema_version !== 1 ||
    typeof value.source_id !== "string" ||
    !/^[A-Za-z0-9_.:-]{1,64}$/.test(value.source_id) ||
    !uuid(value.event_id) ||
    !uuid(value.gateway_request_id) ||
    !nullable(value.backend_request_id, uuid) ||
    !decimalId(value.user_id) ||
    !decimalId(value.model_id) ||
    !nullable(value.session_id, uuid) ||
    !member(value.protocol, ["CHAT", "RESPONSES"]) ||
    !member(value.event_kind, ["DECISION", "FINAL", "DRAIN"]) ||
    !integer(value.event_version, 1) ||
    !integer(value.policy_version) ||
    !digest(value.builtin_digest) ||
    !stamp(value.request_started_at) ||
    !stamp(value.occurred_at) ||
    !stamp(value.received_at) ||
    !validMatchedWords(value.matched_words, value.stage_results) ||
    !integer(value.hit_count) ||
    typeof value.hit_count_truncated !== "boolean" ||
    typeof value.forwarded !== "boolean" ||
    !member(value.drain_status, [
      "NOT_REQUIRED",
      "RUNNING",
      "FINISHED",
      "TIMED_OUT",
      "LIMITED",
      "DISCONNECTED",
    ]) ||
    !Array.isArray(value.rule_refs) ||
    value.rule_refs.length > 20 ||
    !value.rule_refs.every(
      (ref) => typeof ref === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(ref),
    ) ||
    !validConversation(value.conversation) ||
    !member(value.association_status, ["ASSOCIATED", "UNASSOCIATED"]) ||
    !nullable(value.audit_request_id, uuid) ||
    !object(value.stage_results) ||
    !object(value.stage_versions)
  )
    return false;
  const states = value.stage_results,
    versions = value.stage_versions,
    version = value.event_version;
  return ["input", "output"].every(
    (stage) =>
      contentSafetyStates.some((state) => state === states[stage]) &&
      integer(versions[stage]) &&
      Number(versions[stage]) <= version &&
      (states[stage] === "UNREPORTED") === (versions[stage] === 0),
  );
}

function parseEventPage(value: unknown, limit: number): ContentSafetyEventPage {
  if (
    !object(value) ||
    !Array.isArray(value.items) ||
    value.items.length > limit ||
    !value.items.every(validEvent) ||
    !nullable(
      value.next_cursor,
      (cursor) =>
        typeof cursor === "string" &&
        cursor.length > 0 &&
        cursor.length <= 2048,
    ) ||
    !details(value.details_status)
  )
    throw malformed();
  return value as ContentSafetyEventPage;
}

function eventConfig(
  query: { tenant_id?: number; cursor?: string; limit: number },
  signal?: AbortSignal,
) {
  if (!integer(query.limit, 1) || query.limit > 100)
    throw new Error("Invalid DSH content safety page limit");
  return {
    params: query,
    signal,
    preserveError: true,
    headers: { "Cache-Control": "no-store" },
  };
}

export async function getAuditSafetyEvents(
  requestId: string,
  query: { tenant_id?: number; cursor?: string; limit: number },
  signal?: AbortSignal,
): Promise<ContentSafetyEventPage> {
  const value: unknown = await request.get(
    audit +
      "/requests/" +
      encodeURIComponent(requestId) +
      "/content-safety-events",
    eventConfig(query, signal),
  );
  return parseEventPage(value, query.limit);
}
