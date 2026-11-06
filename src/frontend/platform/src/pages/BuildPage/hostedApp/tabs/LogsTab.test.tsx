import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"
import { LogsTab } from "./LogsTab"

const mock = vi.hoisted(() => ({
  logs: vi.fn(async () => ({ lines: [] })),
  t: (key: string, options?: { lines?: number }) => options?.lines ? `Last ${options.lines} lines` : key,
}))
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mock.t }) }))
vi.mock("@/controllers/API/hostedApp", () => ({
  getHostedAppLogsApi: mock.logs, getHostedAppErrorCode: () => undefined,
  getHostedAppErrorMessage: () => "", HOSTED_APP_ERROR: { LOG_FORBIDDEN: 16161 },
}))
vi.mock("@/components/bs-ui/calendar/datePicker", () => ({ DatePicker: () => null }))

describe("run log line limit", () => {
  it("keeps the selected label and requests the new limit", async () => {
    render(<LogsTab appId="app" />)
    const picker = screen.getByRole("combobox", { name: "hostedApp.logs.tail" })
    expect(picker).toHaveTextContent("Last 500 lines")
    fireEvent.click(picker)
    fireEvent.click(await screen.findByRole("option", { name: "Last 2000 lines" }))
    expect(picker).toHaveTextContent("Last 2000 lines")
    fireEvent.click(screen.getByRole("button", { name: "hostedApp.logs.refresh" }))
    await waitFor(() => expect(mock.logs).toHaveBeenLastCalledWith("app", expect.objectContaining({ tail: 2000 })))
  })
})
