/**
 * `GET /api/v1/dev-toolkit/versions` (F053 design D10).
 *
 * The endpoint is anonymous and is only mounted where the open-capability layer
 * is deployed, so every field here is public information: addresses and version
 * numbers, never a credential.
 */

export interface DevToolkitCliArtifact {
  version: string
  min_compatible: string
  filename: string
  sha256: string
  /** A path, not an absolute URL — the browser joins it to its own origin. */
  download_path: string
}

export interface DevToolkitMcpFace {
  url: string
  transport: string
  auth: string
}

export interface DevToolkitModelFace {
  /** OpenAI-compatible base URL, produced by the backend (F051 AC-30). */
  base_url: string
  protocol: string
  auth: string
}

export interface DevToolkitVersions {
  cli: DevToolkitCliArtifact | null
  sdk: {
    version: string | null
    min_compatible: string | null
    download_path: string | null
  }
  mcp: DevToolkitMcpFace | null
  model: DevToolkitModelFace | null
  platform: {
    version: string
    /**
     * The address this deployment answers at, resolved by the backend from the
     * same producer as `mcp` / `model`. Prefer it over `window.location.origin`
     * for anything a developer will run: behind a gateway or a path prefix the
     * origin is missing that prefix. Optional so an older payload still parses.
     */
    base_url?: string | null
    open_platform_enabled: boolean
    app_runtime_enabled: boolean
  }
  /** Null when healthy; a readable reason when an artifact was not shipped. */
  notice: string | null
}
