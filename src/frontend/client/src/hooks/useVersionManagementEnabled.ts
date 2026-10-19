import { useRecoilValue } from "recoil";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import { useAuthContext } from "~/hooks/AuthContext";

// Returns true when the knowledge version management feature flag is enabled
// in the server-side BishengConfig. Falls back to false when config is not yet
// loaded or the key is absent.
export function useVersionManagementEnabled(): boolean {
  const conf = useRecoilValue(bishengConfState);
  return conf?.knowledges?.version_management?.enabled ?? false;
}

export function usePersonalTokenEnabled(): boolean {
  const conf = useRecoilValue(bishengConfState);
  return conf?.personal_token_enabled ?? false;
}

export function useAiAccessUiEnabled(): boolean {
  const conf = useRecoilValue(bishengConfState);
  const { user } = useAuthContext();
  const externalIds = conf?.ai_access_ui_external_ids;
  const externalId = user?.external_id;
  return typeof externalId === "string" && externalId.length > 0
    && Array.isArray(externalIds) && externalIds.includes(externalId);
}
