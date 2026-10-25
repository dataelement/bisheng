import axios from "@/controllers/request"
import type { DevToolkitVersions } from "@/types/api/devToolkit"

/**
 * Addresses and artifact versions the access-information block shows (F053 T046).
 *
 * Only call this where `open_platform_enabled` is true: the router is not
 * registered otherwise, and the shared response interceptor turns a 404 on a
 * GET into a full-page navigation.
 */
export async function getDevToolkitVersionsApi(): Promise<DevToolkitVersions> {
  return await axios.get("/api/v1/dev-toolkit/versions")
}
