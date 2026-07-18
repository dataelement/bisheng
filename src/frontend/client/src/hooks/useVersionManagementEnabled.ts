import { useRecoilValue } from "recoil";
import { bishengConfState } from "~/pages/appChat/store/atoms";

// Returns true when the knowledge version management feature flag is enabled
// in the server-side BishengConfig. Falls back to false when config is not yet
// loaded or the key is absent.
export function useVersionManagementEnabled(): boolean {
  const conf = useRecoilValue(bishengConfState);
  return conf?.knowledges?.version_management?.enabled ?? false;
}
