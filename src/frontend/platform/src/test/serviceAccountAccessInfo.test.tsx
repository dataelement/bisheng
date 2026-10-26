// F053 T046 — the access-information block on the service-account detail page
// (AC-44) and its one-click copy (AC-45).
//
// The two things worth pinning are the two things that would be silently wrong:
// the block must not appear where the open-capability layer is not deployed
// (and must not even ask for the addresses there — a 404 on a GET navigates the
// whole page away), and the copied text must never carry a key or anything that
// could be exchanged for one.
//
// The shared setup mocks `t` down to the bare key, which would erase the values
// interpolated into the copied lines, so this file substitutes a `t` that keeps
// them. The copy's real wording lives in bs.json and is asserted there.

import { locationContext } from "@/contexts/locationContext"
import { getDevToolkitVersionsApi } from "@/controllers/API/devToolkit"
import { AccessInfoPanel } from "@/pages/SystemPage/components/ServiceAccount/AccessInfoPanel"
import { render, screen, waitFor } from "@/test/test-utils"
import type { DevToolkitVersions } from "@/types/api/devToolkit"
import { copyText } from "@/utils"
import userEvent from "@testing-library/user-event"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import type { ReactElement } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string>) =>
      options ? `${key}|${Object.values(options).join("|")}` : key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}))

vi.mock("@/controllers/API/devToolkit", () => ({
  getDevToolkitVersionsApi: vi.fn(),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({ toast: vi.fn() }))

// `userEvent.setup()` installs its own `navigator.clipboard`, so spying on the
// real one would never see the write. The unit under test is what goes into the
// clipboard, not how it gets there.
vi.mock("@/utils", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  copyText: vi.fn(),
}))

const MCP_URL = "https://kb.example.com/api/v2/mcp"
const MODEL_BASE_URL = "https://kb.example.com/api/v2/model/v1"
const DOWNLOAD_PATH = "/api/v1/dev-toolkit/cli/download"

const versions = (overrides: Partial<DevToolkitVersions> = {}): DevToolkitVersions => ({
  cli: {
    version: "3.0.0",
    min_compatible: "3.0.0",
    filename: "bisheng_cli-3.0.0-py3-none-any.whl",
    sha256: "abc",
    download_path: DOWNLOAD_PATH,
  },
  sdk: { version: null, min_compatible: null, download_path: null },
  mcp: { url: MCP_URL, transport: "streamable-http", auth: "bearer" },
  model: { base_url: MODEL_BASE_URL, protocol: "openai", auth: "bearer" },
  platform: {
    version: "3.0.0",
    base_url: null,
    open_platform_enabled: true,
    app_runtime_enabled: true,
  },
  notice: null,
  ...overrides,
})

const renderPanel = (openPlatformEnabled: boolean, ui: ReactElement = <AccessInfoPanel />) =>
  render(
    <locationContext.Provider value={{ appConfig: { openPlatformEnabled } } as never}>
      {ui}
    </locationContext.Provider>,
  )

const writeText = vi.mocked(copyText)

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getDevToolkitVersionsApi).mockResolvedValue(versions())
})

describe("service-account access information (AC-44)", () => {
  it("shows the four addresses a developer needs, and no key", async () => {
    renderPanel(true)

    expect(
      await screen.findByText("openApiManagement.accessInfo.mcpAddress"),
    ).toBeInTheDocument()
    expect(screen.getByText(MCP_URL)).toBeInTheDocument()
    expect(screen.getByText(MODEL_BASE_URL)).toBeInTheDocument()

    // "It is a link, not a file" — the installer is reachable by clicking it,
    // and its address is joined to the origin the administrator is actually on.
    const download = screen.getByRole("link", {
      name: `${window.location.origin}${DOWNLOAD_PATH}`,
    })
    expect(download).toHaveAttribute("href", `${window.location.origin}${DOWNLOAD_PATH}`)

    // The login guidance names the platform and marks where the key goes.
    expect(
      screen.getByText(
        `bisheng login ${window.location.origin} --api-key openApiManagement.accessInfo.keyPlaceholder`,
      ),
    ).toBeInTheDocument()
  })

  it("builds the login command and the installer link on the address the backend resolved", async () => {
    // A gateway or path-prefix deployment: the browser's origin has no
    // `/bisheng` prefix, so composing these two rows from it would print a
    // login command that 404s right under an MCP address that works.
    const base = "https://portal.example.com/bisheng"
    vi.mocked(getDevToolkitVersionsApi).mockResolvedValue(
      versions({
        platform: {
          version: "3.0.0",
          base_url: base,
          open_platform_enabled: true,
          app_runtime_enabled: true,
        },
      }),
    )
    renderPanel(true)

    expect(
      await screen.findByText(
        `bisheng login ${base} --api-key openApiManagement.accessInfo.keyPlaceholder`,
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole("link")).toHaveAttribute("href", `${base}${DOWNLOAD_PATH}`)
    expect(screen.queryByText(window.location.origin)).not.toBeInTheDocument()
  })

  it("falls back to the browser's origin when the payload carries no base", async () => {
    // An older backend, or a deployment that declared nothing: the origin is
    // then exactly what the backend would have resolved anyway.
    renderPanel(true)
    expect(await screen.findByText(window.location.origin)).toBeInTheDocument()
  })

  it("is absent — and asks for nothing — where the open-capability layer is not deployed", async () => {
    renderPanel(false)

    await waitFor(() => {
      expect(getDevToolkitVersionsApi).not.toHaveBeenCalled()
    })
    expect(
      screen.queryByText("openApiManagement.accessInfo.title"),
    ).not.toBeInTheDocument()
  })

  it("stays out of the way when the platform cannot answer", async () => {
    vi.mocked(getDevToolkitVersionsApi).mockRejectedValue(new Error("boom"))
    renderPanel(true)

    await waitFor(() => {
      expect(getDevToolkitVersionsApi).toHaveBeenCalled()
    })
    expect(
      screen.queryByText("openApiManagement.accessInfo.title"),
    ).not.toBeInTheDocument()
  })

  it("says so when the deployment shipped no installer, instead of an empty row", async () => {
    vi.mocked(getDevToolkitVersionsApi).mockResolvedValue(
      // The backend's own notice string; the panel shows its own copy instead.
      versions({ cli: null, notice: "installer not shipped" }),
    )
    renderPanel(true)

    expect(
      await screen.findByText("openApiManagement.accessInfo.cliMissing"),
    ).toBeInTheDocument()
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })
})

describe("one-click copy (AC-45)", () => {
  it("copies every address, with the key represented only by a placeholder", async () => {
    const user = userEvent.setup()
    renderPanel(true)

    await user.click(await screen.findByRole("button", { name: /accessInfo.copy/ }))

    expect(writeText).toHaveBeenCalledTimes(1)
    const copied = writeText.mock.calls[0][0] as string
    expect(copied).toContain(MCP_URL)
    expect(copied).toContain(MODEL_BASE_URL)
    expect(copied).toContain(`${window.location.origin}${DOWNLOAD_PATH}`)
    expect(copied).toContain("bisheng login")
    expect(copied).toContain("openApiManagement.accessInfo.keyPlaceholder")

    // Nothing in the text is a credential or can be exchanged for one: no key
    // prefix, no bearer header, no session cookie, no one-time link.
    for (const forbidden of [
      "bs-sak-",
      "bs-pat-",
      "bs-app-",
      "Authorization",
      "Bearer",
      "access_token",
    ]) {
      expect(copied).not.toContain(forbidden)
    }
  })

  it("is generated from the current addresses every time, never from a snapshot", async () => {
    const user = userEvent.setup()
    const { unmount } = renderPanel(true)
    await user.click(await screen.findByRole("button", { name: /accessInfo.copy/ }))
    unmount()

    const moved = "https://kb.new.example.com/api/v2/mcp"
    vi.mocked(getDevToolkitVersionsApi).mockResolvedValue(
      versions({ mcp: { url: moved, transport: "streamable-http", auth: "bearer" } }),
    )
    renderPanel(true)
    await user.click(await screen.findByRole("button", { name: /accessInfo.copy/ }))

    expect(writeText).toHaveBeenCalledTimes(2)
    expect(writeText.mock.calls[1][0]).toContain(moved)
    expect(writeText.mock.calls[1][0]).not.toContain(MCP_URL)
  })
})

describe("access-information copy ships in all three languages", () => {
  const accessInfoOf = (locale: string): Record<string, string> => {
    const path = resolve(process.cwd(), "public", "locales", locale, "bs.json")
    const bundle = JSON.parse(readFileSync(path, "utf8")) as Record<
      string,
      Record<string, Record<string, string>>
    >
    return bundle.openApiManagement.accessInfo
  }

  it.each(["zh-Hans", "en-US", "ja"])("%s carries the block's keys", (locale) => {
    const accessInfo = accessInfoOf(locale)
    expect(Object.keys(accessInfo).sort()).toEqual(
      [
        "cliDownload",
        "cliMissing",
        "copy",
        "copyFooter",
        "copyHeader",
        "copyLine",
        "hint",
        "keyPlaceholder",
        "loginCommand",
        "mcpAddress",
        "modelBaseUrl",
        "platformAddress",
        "title",
      ].sort(),
    )
    // The copied line is one template with both slots; a language that lost one
    // would silently drop either every label or every address.
    expect(accessInfo.copyLine).toContain("{{label}}")
    expect(accessInfo.copyLine).toContain("{{value}}")
  })
})
