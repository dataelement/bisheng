import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import Apps from "@/pages/BuildPage/apps"

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  i18n: { loadNamespaces: vi.fn() },
}))

vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get },
  handleUiRequest: (handler: unknown) => handler,
  showApiError: vi.fn(),
}))
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: mocks.i18n }),
}))
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: { role: "user", web_menu: [] } }),
}))
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({ appConfig: { appRuntimeEnabled: true } }),
}))
vi.mock("@/components/bs-comp/permission/useResourceActions", () => ({
  useResourceActions: () => ({ actions: {} }),
  hasResourceAction: () => false,
}))
vi.mock("@/pages/BuildPage/hook", () => ({
  useCreateTemp: () => ({ open: false, flowRef: { current: null }, toggleTempModal: vi.fn() }),
  useQueryLabels: () => ({
    selectLabel: { value: -1 },
    setSelectLabel: vi.fn(),
    filteredOptions: [],
    allOptions: [{ value: -1, label: "All tags" }],
    refetchLabels: vi.fn(),
  }),
}))
vi.mock("@/pages/BuildPage/CreateApp", async () => ({
  default: (await import("react")).forwardRef(() => null),
}))
vi.mock("@/pages/BuildPage/CreateTemp", () => ({ default: () => null }))

beforeEach(() => {
  mocks.get.mockReset().mockResolvedValue({ data: [], page_size: 14, has_more: false, next_cursor: null })
})

function latestQuery() {
  const calls = mocks.get.mock.calls.filter(([url]) => String(url).includes("/workflow/list?"))
  return new URL(calls.at(-1)![0], "http://localhost").searchParams
}

async function selectOption(user: ReturnType<typeof userEvent.setup>, filter: string, option: string) {
  await user.click(screen.getByRole("combobox", { name: filter }))
  await user.click(screen.getByRole("option", { name: option }))
}

it.each([
  ["hostedApp.state.draft", "draft"],
  ["hostedApp.state.online", "online"],
  ["hostedApp.state.pending", "pending_capacity"],
  ["hostedApp.state.stopped", "stopped"],
])("sends the selected hosted state to the list request (%s)", async (label, state) => {
  const user = userEvent.setup()
  render(<MemoryRouter><Apps /></MemoryRouter>)
  await waitFor(() => expect(mocks.get).toHaveBeenCalled())
  await selectOption(user, "build.appTypeFilter", "hostedApp.typeName")
  await selectOption(user, "tenant.statusFilter", label)
  await waitFor(() => expect(latestQuery().get("app_state")).toBe(state))
  expect(latestQuery().get("flow_type")).toBe("35")
  expect(latestQuery().get("managed")).toBe("true")
  expect(latestQuery().has("status")).toBe(false)

  await selectOption(user, "tenant.statusFilter", "build.allAppStatus")
  await waitFor(() => expect(latestQuery().has("app_state")).toBe(false))
})

it("clears the previous state when switching between hosted and workflow types", async () => {
  const user = userEvent.setup()
  render(<MemoryRouter><Apps /></MemoryRouter>)
  await waitFor(() => expect(mocks.get).toHaveBeenCalled())
  await selectOption(user, "build.appTypeFilter", "hostedApp.typeName")
  await selectOption(user, "tenant.statusFilter", "hostedApp.state.stopped")
  await waitFor(() => expect(latestQuery().get("app_state")).toBe("stopped"))

  await selectOption(user, "build.appTypeFilter", "build.workflow")
  expect(latestQuery().get("flow_type")).toBe("10")
  expect(latestQuery().has("app_state")).toBe(false)
  expect(screen.getByRole("combobox", { name: "tenant.statusFilter" })).toHaveTextContent("build.allAppStatus")
  await selectOption(user, "tenant.statusFilter", "build.offline")
  expect(latestQuery().get("status")).toBe("1")

  await selectOption(user, "build.appTypeFilter", "hostedApp.typeName")
  expect(latestQuery().has("status")).toBe(false)
  expect(latestQuery().has("app_state")).toBe(false)
  expect(screen.getByRole("combobox", { name: "tenant.statusFilter" })).toHaveTextContent("build.allAppStatus")
})
