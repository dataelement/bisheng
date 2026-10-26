/**
 * T091 — the entry QR code on the publish tab.
 *
 * The contract is byte-for-byte equality: whatever the QR code encodes is
 * exactly what "copy link" copies, and both come from `app.entry_url` as the
 * backend sent it (never composed from `location.origin`). `qrcode.react` is
 * mocked so the encoded value is readable off the DOM instead of by decoding
 * an SVG.
 */
import type { HostedAppDetail } from "@/controllers/API/hostedApp"
import { fireEvent, render, screen } from "@/test/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"
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

  it("encodes exactly the address the copy button copies", async () => {
    render(
      <PublishTab app={buildApp()} instance={null} onChanged={() => {}} />,
    )

    const qr = screen.getByTestId("qr-svg")
    expect(qr.getAttribute("data-value")).toBe(ENTRY_URL)

    fireEvent.click(screen.getByText("hostedApp.publish.copy"))
    await vi.waitFor(() => expect(copyText).toHaveBeenCalledTimes(1))
    expect(copyText).toHaveBeenCalledWith(ENTRY_URL)
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
      ENTRY_URL,
    )
    expect(screen.getByText(ENTRY_URL)).toBeInTheDocument()
    expect(
      screen.getByText("hostedApp.publish.entryInactive"),
    ).toBeInTheDocument()
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
