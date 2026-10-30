import { act, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import userEvent from "@testing-library/user-event"
import { HostedAppCard } from "@/pages/BuildPage/HostedAppCard"
import { getHostedAppVersionsApi, type HostedAppVersion } from "@/controllers/API/hostedApp"

vi.mock("@/controllers/API/hostedApp", () => ({ getHostedAppVersionsApi: vi.fn() }))
vi.mock("react-router-dom", () => ({ useNavigate: () => vi.fn() }))
vi.mock("@/components/bs-comp/cardComponent", () => ({ default: ({ headSelecter }: { headSelecter: React.ReactNode }) => <div>{headSelecter}</div> }))
vi.mock("@/pages/BuildPage/useHostedAppActions", () => ({ useHostedAppActions: () => ({}) }))

const version = (no: number): HostedAppVersion => ({ version_id: `v${no}`, version_no: no, is_current: true, is_pending: false, kind: "initial", terminal_state: "online", submitted_at: null })
const card = (id = "app", online = false) => <HostedAppCard item={{ id, name: id, app_state: online ? "online" : "draft" }} currentUser={{ user_id: 1 }} isAdmin canDelete={false} canSwitch={false} canManagePermission={false} onPermission={vi.fn()} onChanged={vi.fn()} />
beforeEach(() => vi.mocked(getHostedAppVersionsApi).mockReset())

it.each([false, true])("loads the current version on entry without opening the dropdown (online=%s)", async online => {
  vi.mocked(getHostedAppVersionsApi).mockResolvedValue([version(3)])
  render(card("app", online))
  expect(await screen.findByText("v3")).toBeInTheDocument()
  expect(getHostedAppVersionsApi).toHaveBeenCalledWith("app")
  if (online) expect(screen.getByRole("combobox")).toBeDisabled()
})

it("ignores an old app response after the card changes to another application", async () => {
  let finishOld!: (rows: HostedAppVersion[]) => void
  vi.mocked(getHostedAppVersionsApi).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    .mockResolvedValueOnce([version(4)])
  const view = render(card("old"))
  await waitFor(() => expect(getHostedAppVersionsApi).toHaveBeenCalledWith("old"))
  view.rerender(card("new"))
  expect(await screen.findByText("v4")).toBeInTheDocument()
  await act(async () => finishOld([version(2)]))
  expect(screen.queryByText("v2")).toBeNull()
  expect(screen.getByText("v4")).toBeInTheDocument()
})

it("allows retrying a failed initial load by opening the dropdown", async () => {
  vi.mocked(getHostedAppVersionsApi).mockRejectedValueOnce(new Error("unavailable")).mockResolvedValueOnce([version(5)])
  render(card())
  expect(await screen.findByText("hostedApp.version.loadFailed")).toBeInTheDocument()
  const trigger = screen.getByRole("combobox")
  await userEvent.click(trigger)
  await waitFor(() => expect(trigger).toHaveTextContent("v5"))
  expect(getHostedAppVersionsApi).toHaveBeenCalledTimes(2)
})
