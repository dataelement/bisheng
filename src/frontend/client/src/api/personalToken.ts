import request from "./request";

interface ApiEnvelope<T> {
  status_code: number;
  data: T;
}

export interface PersonalTokenItem {
  id: number;
  name: string;
  key_mask: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  is_valid: boolean;
  create_time: string | null;
}

export interface PersonalTokenStatus {
  enabled: boolean;
  token: PersonalTokenItem | null;
  holder_is_admin: boolean;
}

export interface PersonalTokenIssued extends PersonalTokenItem {
  plaintext: string;
  holder_is_admin: boolean;
}

export interface PersonalTokenInstallPrompt {
  prompt: string;
  skill_pack_url: string;
}

function dataOf<T>(response: ApiEnvelope<T>): T {
  return response.data;
}

type RequestErrorOptions = NonNullable<Parameters<typeof request.get>[1]>;

const rejectBusinessErrors: RequestErrorOptions = { skip403Redirect: true };

export function getPersonalTokenGuideUrls(origin: string) {
  return {
    skillPackUrl: new URL(
      "/api/v1/open-api/skill-packs/bisheng-knowledge-search",
      origin,
    ).href,
    tokenPageUrl: new URL("/workspace/settings/account?api-token=1", origin).href,
    retrieveUrl: new URL("/api/v2/filelib/retrieve", origin).href,
  };
}

export async function getPersonalTokenStatusApi(): Promise<PersonalTokenStatus> {
  return dataOf(
    await request.get<ApiEnvelope<PersonalTokenStatus>>(
      "/api/v1/me/api-token",
      rejectBusinessErrors,
    ),
  );
}

export async function issuePersonalTokenApi(): Promise<PersonalTokenIssued> {
  return dataOf(await request.post("/api/v1/me/api-token", undefined, rejectBusinessErrors));
}

export async function deletePersonalTokenApi(): Promise<{ revoked: number }> {
  return dataOf(
    await request.delete<ApiEnvelope<{ revoked: number }>>(
      "/api/v1/me/api-token",
      rejectBusinessErrors,
    ),
  );
}

export async function getPersonalTokenInstallPromptApi(): Promise<PersonalTokenInstallPrompt> {
  return dataOf(
    await request.get<ApiEnvelope<PersonalTokenInstallPrompt>>(
      "/api/v1/me/api-token/install-prompt",
      rejectBusinessErrors,
    ),
  );
}
