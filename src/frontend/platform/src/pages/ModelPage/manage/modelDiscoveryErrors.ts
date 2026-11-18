/** Why a vendor model list could not be fetched, as a `model.discoveryError_<reason>` suffix. */
const discoveryReasons = new Set([
  "auth",
  "timeout",
  "unsupported",
  "address",
  "connection",
  "format",
  "limit",
  "credentials",
  "workspace",
  "resource",
  "region",
  "rate_limit",
]);

export function discoveryFailureReason(
  failure: unknown,
  depth = 0,
): string | undefined {
  if (!failure || typeof failure !== "object" || depth > 2) return undefined;
  const record = failure as {
    kind?: string;
    code?: string;
    message?: string;
    httpStatus?: number;
    cause?: unknown;
    data?: { reason?: string };
    response?: { status?: number; data?: { data?: { reason?: string } } };
  };
  const reason = record.data?.reason ?? record.response?.data?.data?.reason;
  if (reason && discoveryReasons.has(reason)) return reason;
  const status = record.httpStatus ?? record.response?.status;
  if (
    record.kind === "timeout" ||
    record.code === "ECONNABORTED" ||
    record.code === "ETIMEDOUT" ||
    status === 408 ||
    status === 504
  )
    return "timeout";
  if (
    record.kind === "network" ||
    record.code === "ERR_NETWORK" ||
    record.code === "ERR_INTERNET_DISCONNECTED" ||
    status === 0 ||
    status === 502 ||
    status === 503
  )
    return "connection";
  const message = typeof record.message === "string" ? record.message : "";
  if (/timeout of \d+ms exceeded|ECONNABORTED|ETIMEDOUT/i.test(message))
    return "timeout";
  if (
    /Network Error|ERR_NETWORK|ERR_INTERNET_DISCONNECTED|Failed to fetch/i.test(
      message,
    )
  )
    return "connection";
  return discoveryFailureReason(record.cause, depth + 1);
}
