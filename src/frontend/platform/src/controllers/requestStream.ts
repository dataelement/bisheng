import request, {
  handleRequestError,
  handleRequestResponse,
  requestAuthHeaders,
} from "./request";

export async function requestStream(
  url: string,
  signal?: AbortSignal,
): Promise<ReadableStream<Uint8Array>> {
  const sharedBase = (request.defaults.baseURL || "/").replace(/\/?$/, "/");
  const target = new URL(
    url.replace(/^\//, ""),
    new URL(sharedBase, location.origin),
  );
  const config = { url, method: "post" };
  let response: Response;
  try {
    response = await fetch(target, {
      method: "POST",
      credentials: "include",
      signal,
      headers: {
        ...requestAuthHeaders(url),
        "Content-Type": "application/json",
        Accept: "application/x-ndjson",
      },
      body: "{}",
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    await handleRequestError({ config, message: "Network unavailable" });
    throw new Error("Stream unavailable");
  }
  if (
    response.ok &&
    response.headers.get("content-type")?.startsWith("application/x-ndjson") &&
    response.body
  ) {
    return response.body;
  }
  const reader = response.body?.getReader();
  let text = "";
  let size = 0;
  const decoder = new TextDecoder();
  try {
    while (reader) {
      const item = await reader.read();
      if (item.done) break;
      size += item.value.byteLength;
      if (size > 65536) break;
      text += decoder.decode(item.value, { stream: true });
    }
  } finally {
    await reader?.cancel();
    reader?.releaseLock();
  }
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    data = {
      status_code: response.status,
      status_message: "Stream unavailable",
    };
  }
  if (response.ok) {
    await handleRequestResponse({
      config,
      status: response.status,
      data,
      request: { responseURL: target.href },
    });
  } else {
    await handleRequestError({
      config,
      response: { status: response.status, data },
      message: "Stream unavailable",
    });
  }
  throw new Error("Unexpected stream response");
}
