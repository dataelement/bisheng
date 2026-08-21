import ApiRateLimit from "@/pages/SystemPage/components/ApiRateLimit"
import ApiRateLimitRoutePicker from "@/pages/SystemPage/components/ApiRateLimitRoutePicker"
import {
  getApiRateLimitConfigApi,
  getApiRateLimitRoutesApi,
  updateApiRateLimitConfigApi
} from "@/controllers/API/apiRateLimit"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { act, render, screen, within } from "@/test/test-utils"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/apiRateLimit", () => ({
  getApiRateLimitConfigApi: vi.fn(),
  getApiRateLimitRoutesApi: vi.fn(),
  updateApiRateLimitConfigApi: vi.fn()
}))

vi.mock("@/components/bs-icons", () => ({
  DropDownIcon: () => <span data-testid="dropdown-icon" />,
  LoadIcon: () => <span data-testid="loading-icon" />,
  PlusIcon: () => <span data-testid="plus-icon" />,
  SearchIcon: () => <span data-testid="search-icon" />,
  TrashIcon: () => <span data-testid="trash-icon" />
}))

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn()
}))

const routes = Array.from({ length: 11 }, (_, index) => ({
  id: `route-${index}`,
  match_type: "METHOD_PATH" as const,
  method: "GET" as const,
  path: `/api/v1/items/${index}`,
  limits: { second: index + 1, minute: null, hour: null, day: null },
  message: index === 0 ? "first route message" : ""
}))

function PrefixRoutePickerHarness() {
  const [path, setPath] = useState("")

  return (
    <ApiRateLimitRoutePicker
      ruleId="prefix-rule"
      matchType="PREFIX"
      path={path}
      onPathChange={setPath}
      onRouteSelect={(route) => setPath(route.path)}
    />
  )
}

describe("API rate limit settings", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getApiRateLimitConfigApi).mockResolvedValue({
      schema_version: 1,
      revision: 2,
      global: {
        limits: { second: 2, minute: null, hour: null, day: null },
        message: "busy"
      },
      routes,
      updated_at: null,
      updated_by: 1
    })
    vi.mocked(updateApiRateLimitConfigApi).mockResolvedValue({} as never)
    vi.mocked(getApiRateLimitRoutesApi).mockResolvedValue({
      items: [
        {
          method: "GET",
          path: "/api/v1/knowledge/{knowledge_id}",
          tags: ["Knowledge"],
          primary_tag: "Knowledge",
          name: "get_knowledge",
          summary: "Get knowledge"
        },
        {
          method: "POST",
          path: "/api/v1/workflow/run",
          tags: ["Workflow"],
          primary_tag: "Workflow",
          name: "run_workflow",
          summary: "Run workflow"
        }
      ],
      total: 2,
      page: 1,
      page_size: 50,
      total_pages: 1,
      categories: ["Knowledge", "Workflow"]
    })
  })

  it("renders a paginated route table and filters it by keyword", async () => {
    const user = userEvent.setup()
    render(<ApiRateLimit />)

    expect(
      await screen.findByText("system.apiRateLimit.globalTitle")
    ).toBeInTheDocument()
    expect(screen.getByText("system.apiRateLimit.addRoute")).toBeInTheDocument()
    expect(screen.getByText("/api/v1/items/0")).toBeInTheDocument()
    expect(screen.queryByText("/api/v1/items/10")).not.toBeInTheDocument()

    await user.click(screen.getByLabelText("Go to next page"))
    expect(screen.getByText("/api/v1/items/10")).toBeInTheDocument()

    await user.type(
      screen.getByPlaceholderText("system.apiRateLimit.searchPlaceholder"),
      "items/0"
    )
    await user.click(screen.getByText("system.apiRateLimit.query"))
    expect(screen.getByText("/api/v1/items/0")).toBeInTheDocument()
    expect(screen.queryByText("/api/v1/items/10")).not.toBeInTheDocument()
    expect(getApiRateLimitConfigApi).toHaveBeenCalledOnce()
  })

  it("uses the same dialog for adding and editing route rules", async () => {
    const user = userEvent.setup()
    render(<ApiRateLimit />)
    await screen.findByText("/api/v1/items/0")

    await user.click(screen.getByText("system.apiRateLimit.addRoute"))
    let dialog = screen.getByRole("dialog")
    expect(
      within(dialog).getByText("system.apiRateLimit.createRoute")
    ).toBeInTheDocument()
    await user.click(
      within(dialog)
        .getAllByText("system.apiRateLimit.routeCatalog.manualInput")
        .at(-1)!
    )
    const createPath = within(dialog).getByPlaceholderText(
      "system.apiRateLimit.pathPlaceholder"
    )
    expect(createPath).toHaveValue("")
    await user.type(createPath, "/api/v1/items/new")
    await user.click(within(dialog).getByText("confirmButton"))
    expect(screen.getByText("/api/v1/items/new")).toBeInTheDocument()

    await user.click(screen.getByLabelText("Go to previous page"))

    await user.click(screen.getAllByText("system.apiRateLimit.editRoute")[0])
    dialog = screen.getByRole("dialog")
    expect(
      within(dialog).getByText("system.apiRateLimit.editRoute")
    ).toBeInTheDocument()
    await user.click(
      within(dialog).getByText("system.apiRateLimit.routeCatalog.manualInput")
    )
    const editPath = within(dialog).getByPlaceholderText(
      "system.apiRateLimit.pathPlaceholder"
    )
    expect(editPath).toHaveValue("/api/v1/items/0")
    await user.clear(editPath)
    await user.type(editPath, "/api/v1/items/edited")
    await user.click(within(dialog).getByText("confirmButton"))
    expect(screen.getByText("/api/v1/items/edited")).toBeInTheDocument()
    expect(screen.queryByText("/api/v1/items/0")).not.toBeInTheDocument()
  })

  it("searches categorized routes and fills method and path from the selected route", async () => {
    const user = userEvent.setup()
    render(<ApiRateLimit />)
    await screen.findByText("/api/v1/items/0")

    await user.click(screen.getByText("system.apiRateLimit.addRoute"))
    const dialog = screen.getByRole("dialog")
    await user.click(
      within(dialog).getByLabelText(
        "system.apiRateLimit.routeCatalog.selectRoute"
      )
    )

    expect(await within(dialog).findByText("Knowledge")).toBeInTheDocument()
    await user.type(
      within(dialog).getByPlaceholderText(
        "system.apiRateLimit.routeCatalog.searchPlaceholder"
      ),
      "workflow"
    )
    await user.click(
      within(dialog).getAllByText("system.apiRateLimit.query")[0]
    )

    expect(getApiRateLimitRoutesApi).toHaveBeenLastCalledWith(
      expect.objectContaining({
        keyword: "workflow",
        page: 1,
        page_size: 50
      })
    )
    await user.click(within(dialog).getByText("/api/v1/workflow/run"))
    expect(within(dialog).getByText("/api/v1/workflow/run")).toBeInTheDocument()
    expect(within(dialog).getByText("POST")).toBeInTheDocument()
  })

  it("falls back to manual input without clearing the draft when route loading fails", async () => {
    const user = userEvent.setup()
    vi.mocked(getApiRateLimitRoutesApi).mockRejectedValueOnce(
      new Error("network error")
    )
    render(<ApiRateLimit />)
    await screen.findByText("/api/v1/items/0")

    await user.click(screen.getByText("system.apiRateLimit.addRoute"))
    const dialog = screen.getByRole("dialog")
    await user.click(
      within(dialog).getByLabelText(
        "system.apiRateLimit.routeCatalog.selectRoute"
      )
    )

    expect(
      await within(dialog).findByText(
        "system.apiRateLimit.routeCatalog.loadFailed"
      )
    ).toBeInTheDocument()
    await user.click(
      within(dialog)
        .getAllByText("system.apiRateLimit.routeCatalog.manualInput")
        .at(-1)!
    )
    expect(
      within(dialog).getByPlaceholderText("system.apiRateLimit.pathPlaceholder")
    ).toHaveValue("")
  })

  it("uses a selected catalog route as an editable prefix suggestion", async () => {
    const user = userEvent.setup()
    render(<PrefixRoutePickerHarness />)

    await user.click(
      screen.getByLabelText("system.apiRateLimit.routeCatalog.selectRoute")
    )
    await user.click(
      await screen.findByText("/api/v1/knowledge/{knowledge_id}")
    )

    expect(
      screen.getByPlaceholderText("system.apiRateLimit.pathPlaceholder")
    ).toHaveValue("/api/v1/knowledge/{knowledge_id}")
  })

  it("deletes a route from the list only after confirmation", async () => {
    const user = userEvent.setup()
    render(<ApiRateLimit />)
    await screen.findByText("/api/v1/items/0")

    await user.click(screen.getAllByText("system.apiRateLimit.deleteRoute")[0])
    expect(bsConfirm).toHaveBeenCalledOnce()
    const confirmOptions = vi.mocked(bsConfirm).mock.calls[0][0]
    await act(async () => {
      await confirmOptions.onOk?.(vi.fn())
    })

    expect(screen.queryByText("/api/v1/items/0")).not.toBeInTheDocument()
  })
})
