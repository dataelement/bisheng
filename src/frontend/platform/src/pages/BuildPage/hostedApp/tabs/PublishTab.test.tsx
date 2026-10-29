/**
 * T091 — the entry QR code on the publish tab.
 *
 * The contract is byte-for-byte equality: whatever the QR code encodes is
 * exactly what "copy link" copies and "open" follows, using the current
 * browser origin rather than the configured backend host. `qrcode.react` is
 * mocked so the encoded value is readable off the DOM instead of by decoding
 * an SVG.
 */
import type { HostedAppDetail } from "@/controllers/API/hostedApp"
import { fireEvent, render, screen } from "@/test/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { PublishTab } from "./PublishTab"

const copyText = vi.fn()
vi.mock("@/utils", () => ({
  copyText: (...args: unknown[]) => copyText(...args),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}))

vi.mock("../../useHostedAppActions", () => ({
  useHostedAppActions: () => ({
    stopApp: vi.fn(),
    resumeApp: vi.fn(),
    manualPublishApp: vi.fn(),
  }),
}))

vi.mock("qrcode.react", () => ({
  QRCodeSVG: (props: { value: string; size?: number }) => (
    <svg data-testid="qr-svg" data-value={props.value} width={props.size} />
  ),
}))

const ENTRY_URL = "https://bisheng.example.com/apps/demo-slug/"
const browserEntryUrl = () => `${window.location.origin}/apps/demo-slug/`

function buildApp(overrides: Partial<HostedAppDetail> = {}): HostedAppDetail {
  return {
    app_id: "app-1",
    slug: "demo-slug",
    name: "Demo",
    description: null,
    logo: null,
    state: "online",
    owner_user_id: 1,
    tenant_id: 1,
    current_version_id: "v1",
    pending_version_id: null,
    entry_url: ENTRY_URL,
    create_time: null,
    update_time: null,
    ...overrides,
  }
}

describe("PublishTab entry QR code", () => {
  beforeEach(() => {
    copyText.mockReset()
    copyText.mockResolvedValue(undefined)
  })
  afterEach(() => vi.unstubAllGlobals())

  it("encodes exactly the address the copy button copies", async () => {
    render(<PublishTab app={buildApp()} instance={null} onChanged={() => {}} />)

    const qr = screen.getByTestId("qr-svg")
    expect(qr.getAttribute("data-value")).toBe(browserEntryUrl())
    expect(screen.getByText(browserEntryUrl())).toBeInTheDocument()
    expect(
      screen.getByRole("link", { name: "hostedApp.publish.open" }),
    ).toHaveAttribute("href", browserEntryUrl())
    expect(screen.queryByText(ENTRY_URL)).toBeNull()

    fireEvent.click(screen.getByText("hostedApp.publish.copy"))
    await vi.waitFor(() => expect(copyText).toHaveBeenCalledTimes(1))
    expect(copyText).toHaveBeenCalledWith(browserEntryUrl())
    expect(screen.getByText("hostedApp.publish.qrLabel")).toBeInTheDocument()
  })

  it("keeps the QR code and the link on the same visibility rule when offline", () => {
    render(
      <PublishTab
        app={buildApp({ state: "stopped" })}
        instance={null}
        onChanged={() => {}}
      />,
    )

    // The link is still rendered for a stopped app, so the code is too; the
    // "not running" hint covers both.
    expect(screen.getByTestId("qr-svg").getAttribute("data-value")).toBe(
      browserEntryUrl(),
    )
    expect(screen.getByText(browserEntryUrl())).toBeInTheDocument()
    expect(
      screen.getByText("hostedApp.publish.entryInactive"),
    ).toBeInTheDocument()
  })

  it("keeps the browser deployment prefix and accepts a relative backend entry", () => {
    vi.stubGlobal("__APP_ENV__", { BASE_URL: "/custom" })
    render(
      <PublishTab
        app={buildApp({ entry_url: "/apps/demo-slug" })}
        instance={null}
        onChanged={() => {}}
      />,
    )

    const expected = `${window.location.origin}/custom/apps/demo-slug/`
    expect(screen.getByTestId("qr-svg")).toHaveAttribute("data-value", expected)
    expect(
      screen.getByRole("link", { name: "hostedApp.publish.open" }),
    ).toHaveAttribute("href", expected)
  })

  it("renders no QR code when the backend sent no entry address", () => {
    render(
      <PublishTab
        app={buildApp({ entry_url: "" })}
        instance={null}
        onChanged={() => {}}
      />,
    )

    expect(screen.queryByTestId("qr-svg")).toBeNull()
    expect(screen.queryByTestId("hosted-app-entry-qr")).toBeNull()
  })
})
