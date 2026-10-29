import {
  getDshSafetyCapabilities,
  getDshSensitivePolicy,
  saveDshSensitivePolicy,
} from "@/controllers/API/dshContentSafety";
import type {
  DshSafetyLimits,
  DshSensitivePolicyCommand,
} from "@/types/dshContentSafety";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const policyKey = (tenantId?: number) =>
  ["dsh-content-safety", "settings", tenantId] as const;
const capabilityKey = (tenantId?: number) =>
  ["dsh-content-safety", "capabilities", tenantId] as const;

export function useDshContentSafety(tenantId?: number) {
  const client = useQueryClient();
  const validTenant = Number.isSafeInteger(tenantId) && Number(tenantId) > 0;
  const capabilities = useQuery({
    queryKey: capabilityKey(tenantId),
    queryFn: ({ signal }) => getDshSafetyCapabilities(Number(tenantId), signal),
    enabled: validTenant,
    retry: false,
    cacheTime: 0,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const ready =
    capabilities.isSuccess &&
    capabilities.data?.available === true &&
    capabilities.data.configuration_ready === true &&
    capabilities.data.enabled === true;
  const policy = useQuery({
    queryKey: policyKey(tenantId),
    queryFn: ({ signal }) => getDshSensitivePolicy(Number(tenantId), signal),
    enabled: validTenant && ready,
    retry: false,
    cacheTime: 0,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const mutation = useMutation({
    mutationFn: (command: DshSensitivePolicyCommand) =>
      saveDshSensitivePolicy(Number(tenantId), command),
    retry: false,
    onSuccess: (value) => client.setQueryData(policyKey(tenantId), value),
  });
  async function refresh() {
    if (!validTenant) return undefined;
    const result = await capabilities.refetch();
    if (
      result.isError ||
      !result.data?.available ||
      !result.data.configuration_ready ||
      !result.data.enabled
    )
      return undefined;
    const settings = await policy.refetch();
    return settings.isError ? undefined : settings.data;
  }
  return { capabilities, policy, mutation, ready, refresh };
}

export function validateDshSensitivePolicy(
  command: DshSensitivePolicyCommand,
  limits: DshSafetyLimits,
): string | null {
  if (
    new TextEncoder().encode(command.custom_words).length >
    limits.custom_words_max_bytes
  )
    return "custom_words_too_large";
  if (Array.from(command.auto_reply).length > 2048) return "reply_too_long";
  if (!command.enabled) return null;
  if (!command.input_enabled && !command.output_enabled)
    return "checks_required";
  if (!command.auto_reply.trim()) return "reply_required";
  if (
    !command.words_types.length ||
    (command.words_types.length === 1 &&
      command.words_types[0] === "2" &&
      !command.custom_words.split(/[\n ,，|]/u).some((word) => word.trim()))
  )
    return "words_required";
  // The Gateway remains authoritative for the compiled union, individual word
  // limits and literal matching; the browser does not compile another matcher.
  return null;
}

export function dshSensitivePolicyValidationError(
  error: unknown,
): string | null {
  if (!error || typeof error !== "object" || !("response" in error))
    return null;
  const response = error.response;
  if (!response || typeof response !== "object" || !("data" in response))
    return null;
  const data = response.data;
  if (!data || typeof data !== "object" || !("status_message" in data))
    return null;
  const code = data.status_message;
  if (code === "custom_words_too_large" || code === "word_too_long")
    return code;
  if (code === "effective_words_too_large") return "too_many_words";
  if (code === "words_empty" || code === "word_sources_invalid")
    return "words_required";
  return null;
}
