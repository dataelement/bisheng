type FailureDescription = { key: string; status?: string };

const modelReasons: Record<string, string> = {
  upstream_timeout: "timeout",
  upstream_connection_failed: "connection",
  upstream_authentication_failed: "authentication",
  upstream_rate_limited: "rate_limit",
  upstream_quota_exhausted: "quota",
  context_length_exceeded: "context_length",
  upstream_server_error: "provider",
  cancelled: "cancelled",
  cancelled_before_upstream: "cancelled",
};
const responseReasons: Record<string, string> = {
  error_response: "error_response",
  peer_disconnected: "peer_disconnected",
  response_cancelled: "response_cancelled",
  send_failed: "send_failed",
  response_interrupted: "response_interrupted",
};

export function auditFailure(
  code: string | null | undefined,
  axis: "model" | "response",
): FailureDescription {
  const status =
    axis === "model"
      ? /^upstream_http_([45]\d{2})$/.exec(code || "")?.[1]
      : undefined;
  if (status) {
    const key =
      (
        {
          "401": "authentication",
          "403": "permission",
          "404": "endpoint",
          "408": "timeout",
          "413": "request_size",
          "422": "parameters",
          "429": "rate_or_quota",
          "504": "timeout",
        } as Record<string, string>
      )[status] || (status.startsWith("5") ? "provider" : "http");
    return { key, status };
  }
  const reasons = axis === "model" ? modelReasons : responseReasons;
  return {
    key: code && Object.hasOwn(reasons, code) ? reasons[code] : "unavailable",
  };
}
