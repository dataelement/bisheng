import { act, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import userEvent from "@testing-library/user-event"
import { createInstance } from "i18next"
import en from "../../public/locales/en-US/bs.json"
import { HostedAppCard } from "@/pages/BuildPage/HostedAppCard"
import { getHostedAppVersionsApi, type HostedAppVersion } from "@/controllers/API/hostedApp"

vi.mock("@/controllers/API/hostedApp", () => ({ getHostedAppVersionsApi: vi.fn() }))
const navigate = vi.hoisted(() => vi.fn())
vi.mock("react-router-dom", () => ({ useNavigate: () => navigate }))
vi.mock("@/components/bs-comp/cardComponent", () => ({ default: ({ headSelecter, onClick }: { headSelecter: React.ReactNode; onClick: () => void }) => <div onClick={onClick}>{headSelecter}</div> }))
vi.mock("@/pages/BuildPage/useHostedAppActions", () => ({ useHostedAppActions: () => ({}) }))
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, values?: { version: string }) => i18n.t(key, values) }),
}))

const i18n = createInstance()
void i18n.init({ lng: "en-US", resources: { "en-US": { translation: en } }, initImmediate: false })

const version = (no: number): HostedAppVersion => ({ version_id: `v${no}`, version_no: no, is_current: true, is_pending: false, kind: "initial", terminal_state: "online", submitted_at: null })
const card = (id = "app", online = false) => <HostedAppCard item={{ id, name: id, app_state: online ? "online" : "draft" }} currentUser={{ user_id: 1 }} isAdmin canDelete={false} canSwitch={false} canManagePermission={false} onPermission={vi.fn()} onChanged={vi.fn()} />
beforeEach(() => {
  vi.mocked(getHostedAppVersionsApi).mockReset()
  navigate.mockClear()
})

it.each([false, true])("shows read-only version text on entry (online=%s)", async online => {
  vi.mocked(getHostedAppVersionsApi).mockResolvedValue([version(3)])
  render(card("app", online))
  expect(await screen.findByText(online ? "Running version v3" : "Latest version v3")).toBeInTheDocument()
  expect(getHostedAppVersionsApi).toHaveBeenCalledWith("app")
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument()
})

it("shows no uploaded code for an empty version list", async () => {
  vi.mocked(getHostedAppVersionsApi).mockResolvedValue([])
  render(card())
  expect(await screen.findByText("No code uploaded")).toBeInTheDocument()
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument()
})

it.each([false, true])("distinguishes the latest upload from the running version (online=%s)", async online => {
  vi.mocked(getHostedAppVersionsApi).mockResolvedValue([
    version(1),
    { ...version(3), is_current: false, is_pending: true },
    { ...version(2), is_current: false },
  ])
  render(card("app", online))
  expect(await screen.findByText(online ? "Running version v1" : "Latest version v3")).toBeInTheDocument()
})

it("does not call a pending upload the running version when no current version is known", async () => {
  vi.mocked(getHostedAppVersionsApi).mockResolvedValue([{ ...version(2), is_current: false }])
  render(card("app", true))
  expect(await screen.findByText("Running version unknown")).toBeInTheDocument()
  expect(screen.queryByText("Running version v2")).not.toBeInTheDocument()
})

it("ignores an old app response after the card changes to another application", async () => {
  let finishOld!: (rows: HostedAppVersion[]) => void
  vi.mocked(getHostedAppVersionsApi).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    .mockResolvedValueOnce([version(4)])
  const view = render(card("old"))
  await waitFor(() => expect(getHostedAppVersionsApi).toHaveBeenCalledWith("old"))
  view.rerender(card("new"))
  expect(await screen.findByText("Latest version v4")).toBeInTheDocument()
  await act(async () => finishOld([version(2)]))
  expect(screen.queryByText("Latest version v2")).toBeNull()
  expect(screen.getByText("Latest version v4")).toBeInTheDocument()
})

it("keeps failures distinct from an empty version list and allows retrying", async () => {
  vi.mocked(getHostedAppVersionsApi).mockRejectedValueOnce(new Error("unavailable")).mockResolvedValueOnce([version(5)])
  render(card())
  expect(await screen.findByText("Failed to load versions")).toBeInTheDocument()
  expect(screen.queryByText("No code uploaded")).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Retry" }))
  expect(await screen.findByText("Latest version v5")).toBeInTheDocument()
  expect(getHostedAppVersionsApi).toHaveBeenCalledTimes(2)
  expect(navigate).not.toHaveBeenCalled()
})
