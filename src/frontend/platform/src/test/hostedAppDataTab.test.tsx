import type {
  HostedAppRowPage,
  HostedAppTable,
  HostedAppTableSchema,
} from "@/controllers/API/hostedAppData"
import {
  exportHostedAppTableApi,
  getHostedAppTableRowsApi,
  getHostedAppTableSchemaApi,
  getHostedAppTablesApi,
  updateHostedAppRowApi,
} from "@/controllers/API/hostedAppData"
import { DataTab } from "@/pages/BuildPage/hostedApp/tabs/DataTab"
import { saveBlob } from "@/pages/BuildPage/hostedApp/tabs/data/dataTabModel"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest"

vi.mock("@/controllers/API/hostedAppData", () => ({
  getHostedAppTablesApi: vi.fn(),
  getHostedAppTableSchemaApi: vi.fn(),
  getHostedAppTableRowsApi: vi.fn(),
  updateHostedAppRowApi: vi.fn(),
  exportHostedAppTableApi: vi.fn(),
}))

// The confirm dialog is a global imperative helper mounted outside React; the
// tests only need "the user pressed OK".
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn(({ onOk }: { onOk?: (next: () => void) => void }) => onOk?.(() => undefined)),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}))

vi.mock("@/pages/BuildPage/hostedApp/tabs/data/dataTabModel", async () => {
  const actual = await vi.importActual<
    typeof import("@/pages/BuildPage/hostedApp/tabs/data/dataTabModel")
  >("@/pages/BuildPage/hostedApp/tabs/data/dataTabModel")
  return { ...actual, saveBlob: vi.fn() }
})

const tables: HostedAppTable[] = [
  { name: "users", column_count: 3 },
  { name: "orders", column_count: 2 },
]

const usersSchema: HostedAppTableSchema = {
  table: "users",
  columns: [
    { name: "id", type: "INTEGER", notnull: false, default: null, pk: 1, editable: true },
    { name: "name", type: "TEXT", notnull: true, default: null, pk: 0, editable: true },
    { name: "note", type: "TEXT", notnull: false, default: null, pk: 0, editable: true },
  ],
  key: { column: "id", kind: "primary_key" },
  editable: true,
}

const usersPage: HostedAppRowPage = {
  rows: [
    { key: 1, values: { id: 1, name: "alice", note: null } },
    { key: 2, values: { id: 2, name: "bob", note: "hi" } },
  ],
  total: 2,
  page: 1,
  size: 50,
  order: "",
}

function envelope(code: number, message = "refused") {
  return { status_code: code, status_message: message, data: null }
}

function renderTab() {
  return render(<DataTab appId="app-1" appName="sales" />)
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(getHostedAppTablesApi as Mock).mockResolvedValue({ tables })
  ;(getHostedAppTableSchemaApi as Mock).mockResolvedValue(usersSchema)
  ;(getHostedAppTableRowsApi as Mock).mockResolvedValue(usersPage)
  ;(updateHostedAppRowApi as Mock).mockResolvedValue({
    table: "users",
    key: 1,
    before: { name: "alice" },
    after: { name: "alicia" },
  })
  ;(exportHostedAppTableApi as Mock).mockResolvedValue(
    new Blob(["id,name\r\n1,alice\r\n"], { type: "text/csv" }),
  )
})

describe("DataTab — table list → rows", () => {
  it("lists the tables, opens the first one and renders its rows", async () => {
    renderTab()
    expect(await screen.findByRole("button", { name: /users/ })).toBeTruthy()
    expect(screen.getByRole("button", { name: /orders/ })).toBeTruthy()

    await waitFor(() =>
      expect(getHostedAppTableRowsApi).toHaveBeenCalledWith("app-1", "users", {
        page: 1,
        size: 50,
        order: undefined,
      }),
    )
    expect(await screen.findByText("alice")).toBeTruthy()
    expect(screen.getByText("bob")).toBeTruthy()
    // NULL is drawn as a marker, never as the word "null".
    expect(screen.queryByText("null")).toBeNull()
    expect(screen.getAllByText("hostedApp.data.nullLabel").length).toBeGreaterThan(0)
  })

  it("switches table on click and restarts at page 1 with no order", async () => {
    ;(getHostedAppTableSchemaApi as Mock).mockImplementation((_app: string, table: string) =>
      Promise.resolve({ ...usersSchema, table }),
    )
    renderTab()
    const user = userEvent.setup()
    await user.click(await screen.findByRole("button", { name: /orders/ }))
    await waitFor(() =>
      expect(getHostedAppTableRowsApi).toHaveBeenLastCalledWith("app-1", "orders", {
        page: 1,
        size: 50,
        order: undefined,
      }),
    )
  })

  it("sorts by a column header and cycles asc → desc → none", async () => {
    renderTab()
    const user = userEvent.setup()
    const header = await screen.findByRole("button", { name: "name" })
    await user.click(header)
    await waitFor(() =>
      expect(getHostedAppTableRowsApi).toHaveBeenLastCalledWith(
        "app-1",
        "users",
        expect.objectContaining({ order: "name" }),
      ),
    )
    await user.click(screen.getByRole("button", { name: "name" }))
    await waitFor(() =>
      expect(getHostedAppTableRowsApi).toHaveBeenLastCalledWith(
        "app-1",
        "users",
        expect.objectContaining({ order: "-name" }),
      ),
    )
    await user.click(screen.getByRole("button", { name: "name" }))
    await waitFor(() =>
      expect(getHostedAppTableRowsApi).toHaveBeenLastCalledWith(
        "app-1",
        "users",
        expect.objectContaining({ order: undefined }),
      ),
    )
  })

  it("shows the empty state when the app has no tables", async () => {
    ;(getHostedAppTablesApi as Mock).mockResolvedValue({ tables: [] })
    renderTab()
    expect(await screen.findByText("hostedApp.data.noTables")).toBeTruthy()
    expect(getHostedAppTableRowsApi).not.toHaveBeenCalled()
  })
})

describe("DataTab — refusals stay inline (design pit 25)", () => {
  it("renders a notice on 16162 instead of throwing the page away", async () => {
    ;(getHostedAppTablesApi as Mock).mockRejectedValue(envelope(16162))
    renderTab()
    expect(await screen.findByText("hostedApp.data.forbidden")).toBeTruthy()
    expect(getHostedAppTableRowsApi).not.toHaveBeenCalled()
  })

  it("treats 16163 (no database yet) as an empty state, not an error", async () => {
    ;(getHostedAppTablesApi as Mock).mockRejectedValue(envelope(16163))
    renderTab()
    expect(await screen.findByText("hostedApp.data.notReady")).toBeTruthy()
  })

  it("shows the backend's message for any other failure", async () => {
    ;(getHostedAppTablesApi as Mock).mockRejectedValue(envelope(16121, "orchestrator down"))
    renderTab()
    expect(await screen.findByText("orchestrator down")).toBeTruthy()
  })
})

describe("DataTab — single-row edit", () => {
  it("sends only the changed columns after confirmation and re-reads the page", async () => {
    renderTab()
    const user = userEvent.setup()
    const editButtons = await screen.findAllByRole("button", { name: "hostedApp.data.edit" })
    await user.click(editButtons[0])

    const dialog = await screen.findByRole("dialog")
    const nameInput = within(dialog).getByLabelText("name") as HTMLInputElement
    expect(nameInput.value).toBe("alice")
    // The key column is not offered as an input.
    expect(within(dialog).queryByLabelText("id")).toBeNull()

    const saveButton = within(dialog).getByRole("button", { name: "hostedApp.data.save" })
    expect(saveButton.hasAttribute("disabled")).toBe(true)

    await user.clear(nameInput)
    await user.type(nameInput, "alicia")
    expect(saveButton.hasAttribute("disabled")).toBe(false)
    await user.click(saveButton)

    await waitFor(() =>
      expect(updateHostedAppRowApi).toHaveBeenCalledWith("app-1", "users", 1, { name: "alicia" }),
    )
    // one load on open + one after the save
    await waitFor(() => expect(getHostedAppTableRowsApi).toHaveBeenCalledTimes(2))
  })

  it("explains a row that moved under the owner (16165) inside the dialog", async () => {
    ;(updateHostedAppRowApi as Mock).mockRejectedValue(envelope(16165))
    renderTab()
    const user = userEvent.setup()
    await user.click((await screen.findAllByRole("button", { name: "hostedApp.data.edit" }))[0])
    const dialog = await screen.findByRole("dialog")
    const nameInput = within(dialog).getByLabelText("name")
    await user.clear(nameInput)
    await user.type(nameInput, "x")
    await user.click(within(dialog).getByRole("button", { name: "hostedApp.data.save" }))
    expect(await within(dialog).findByText("hostedApp.data.rowMoved")).toBeTruthy()
  })

  it("offers no edit button on a table the manager marked read-only", async () => {
    ;(getHostedAppTableSchemaApi as Mock).mockResolvedValue({ ...usersSchema, editable: false })
    ;(getHostedAppTableRowsApi as Mock).mockResolvedValue({
      ...usersPage,
      rows: usersPage.rows.map((row) => ({ ...row, key: null })),
    })
    renderTab()
    expect(await screen.findByText("alice")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "hostedApp.data.edit" })).toBeNull()
    expect(screen.getByText("hostedApp.data.readOnlyTable")).toBeTruthy()
  })
})

describe("DataTab — export", () => {
  it("downloads the backend-produced CSV under the app and table name", async () => {
    renderTab()
    const user = userEvent.setup()
    await screen.findByText("alice")
    await user.click(screen.getByRole("button", { name: /hostedApp.data.export/ }))
    await waitFor(() => expect(exportHostedAppTableApi).toHaveBeenCalledWith("app-1", "users"))
    await waitFor(() => expect(saveBlob).toHaveBeenCalledTimes(1))
    expect((saveBlob as Mock).mock.calls[0][1]).toBe("sales-users.csv")
  })
})
