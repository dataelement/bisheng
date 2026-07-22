import type {
  DeveloperTokenFileSyncTargetDisplay,
  DeveloperTokenFileSyncTargetSpaceGroup,
} from "@/controllers/API/developerToken"
import { getDeveloperTokenFileSyncTargetChildrenApi } from "@/controllers/API/developerToken"
import DeveloperTokenFileSyncTargetTree from "@/pages/SystemPage/components/DeveloperTokenFileSyncTargetTree"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/controllers/API/developerToken", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/controllers/API/developerToken")>()
  return {
    ...actual,
    getDeveloperTokenFileSyncTargetChildrenApi: vi.fn(),
  }
})

const groups: DeveloperTokenFileSyncTargetSpaceGroup[] = [
  {
    space_type: "public",
    spaces: [{ id: 100, name: "Public", selectable: true, has_children: false }],
  },
  {
    space_type: "department",
    spaces: [{ id: 118, name: "Safety", selectable: false, has_children: true }],
  },
]

const staleDisplay: DeveloperTokenFileSyncTargetDisplay = {
  knowledge_id: 118,
  knowledge_name: "Safety",
  target_type: "folder",
  folder_id: 999,
  folder_path: [{ id: 999, name: "Removed" }],
  stale: true,
}

const mockedChildren = vi.mocked(getDeveloperTokenFileSyncTargetChildrenApi)

describe("DeveloperTokenFileSyncTargetTree", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("groups spaces and treats expansion separately from root selection", async () => {
    mockedChildren.mockResolvedValue({
      data: [
        {
          id: 4096,
          name: "Navigation",
          selectable: false,
          navigation_only: true,
          has_children: true,
        },
      ],
      has_more: false,
      next_cursor: null,
      page_size: 50,
    })
    const onChange = vi.fn()

    render(
      <DeveloperTokenFileSyncTargetTree
        tenantId={5}
        userId={7}
        groups={groups}
        value={{ knowledge_id: null, folder_id: null }}
        display={null}
        loading={false}
        error={null}
        onChange={onChange}
        onSearchSpaces={vi.fn()}
      />
    )

    expect(screen.getByText("system.developerToken.fileSync.targetTree.groups.public")).toBeInTheDocument()
    expect(screen.getByText("system.developerToken.fileSync.targetTree.groups.department")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Safety" }))
    expect(onChange).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByText("Navigation")).toBeInTheDocument())
    expect(screen.getByRole("radio", { name: "Navigation" })).toBeDisabled()

    fireEvent.click(screen.getByRole("radio", { name: "Public" }))
    expect(onChange).toHaveBeenCalledWith({ knowledge_id: 100, folder_id: null })
  })

  it("appends folder cursor pages and selects only an authorized directory", async () => {
    mockedChildren
      .mockResolvedValueOnce({
        data: [
          {
            id: 4096,
            name: "Policies",
            selectable: true,
            navigation_only: false,
            has_children: false,
          },
        ],
        has_more: true,
        next_cursor: "next-folder",
        page_size: 1,
      })
      .mockResolvedValueOnce({
        data: [
          {
            id: 4097,
            name: "Notices",
            selectable: true,
            navigation_only: false,
            has_children: false,
          },
        ],
        has_more: false,
        next_cursor: null,
        page_size: 1,
      })
    const onChange = vi.fn()

    render(
      <DeveloperTokenFileSyncTargetTree
        tenantId={5}
        userId={7}
        groups={groups}
        value={{ knowledge_id: 118, folder_id: null }}
        display={null}
        loading={false}
        error={null}
        onChange={onChange}
        onSearchSpaces={vi.fn()}
      />
    )

    fireEvent.click(screen.getByRole("button", { name: "Safety" }))
    await waitFor(() => expect(screen.getByText("Policies")).toBeInTheDocument())
    fireEvent.click(screen.getByRole("button", {
      name: "system.developerToken.fileSync.targetTree.loadMore",
    }))
    await waitFor(() => expect(screen.getByText("Notices")).toBeInTheDocument())

    expect(mockedChildren).toHaveBeenNthCalledWith(2, {
      tenant_id: 5,
      user_id: 7,
      knowledge_id: 118,
      parent_id: undefined,
      cursor: "next-folder",
      page_size: 50,
      signal: expect.any(AbortSignal),
    })
    fireEvent.click(screen.getByRole("radio", { name: "Notices" }))
    expect(onChange).toHaveBeenCalledWith({ knowledge_id: 118, folder_id: 4097 })
  })

  it("shows loading, error, empty, no-permission, and stale states", () => {
    const { rerender } = render(
      <DeveloperTokenFileSyncTargetTree
        tenantId={5}
        userId={7}
        groups={[]}
        value={{ knowledge_id: 118, folder_id: 999 }}
        display={staleDisplay}
        loading
        error={null}
        onChange={vi.fn()}
        onSearchSpaces={vi.fn()}
      />
    )
    expect(screen.getByText("system.developerToken.fileSync.targetTree.loading")).toBeInTheDocument()
    expect(screen.getByText("system.developerToken.fileSync.targetTree.stale")).toBeInTheDocument()

    rerender(
      <DeveloperTokenFileSyncTargetTree
        tenantId={5}
        userId={7}
        groups={[]}
        value={{ knowledge_id: null, folder_id: null }}
        display={null}
        loading={false}
        error="failed"
        onChange={vi.fn()}
        onSearchSpaces={vi.fn()}
      />
    )
    expect(screen.getByText("system.developerToken.fileSync.targetTree.error")).toBeInTheDocument()

    rerender(
      <DeveloperTokenFileSyncTargetTree
        tenantId={5}
        userId={7}
        groups={[]}
        value={{ knowledge_id: null, folder_id: null }}
        display={null}
        loading={false}
        error={null}
        onChange={vi.fn()}
        onSearchSpaces={vi.fn()}
      />
    )
    expect(screen.getByText("system.developerToken.fileSync.targetTree.noPermission")).toBeInTheDocument()
    fireEvent.change(
      screen.getByPlaceholderText("system.developerToken.fileSync.spaceSearchPlaceholder"),
      { target: { value: "missing" } },
    )
    expect(screen.getByText("system.developerToken.fileSync.targetTree.empty")).toBeInTheDocument()

    rerender(
      <DeveloperTokenFileSyncTargetTree
        tenantId={5}
        userId={7}
        groups={[
          {
            space_type: "department",
            spaces: [{ id: 118, name: "Safety", selectable: false, has_children: false }],
          },
        ]}
        value={{ knowledge_id: null, folder_id: null }}
        display={null}
        loading={false}
        error={null}
        onChange={vi.fn()}
        onSearchSpaces={vi.fn()}
      />
    )
    expect(screen.getByText("system.developerToken.fileSync.targetTree.noPermission")).toBeInTheDocument()
  })

  it("ignores an old folder response after the bound user changes", async () => {
    let resolveOld: (value: Awaited<ReturnType<
      typeof getDeveloperTokenFileSyncTargetChildrenApi
    >>) => void = () => undefined
    mockedChildren
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveOld = resolve
      }))
      .mockResolvedValueOnce({
        data: [{
          id: 5000,
          name: "New user folder",
          selectable: true,
          navigation_only: false,
          has_children: false,
        }],
        has_more: false,
        next_cursor: null,
        page_size: 50,
      })
    const props = {
      tenantId: 5,
      groups,
      value: { knowledge_id: null, folder_id: null },
      display: null,
      loading: false,
      error: null,
      onChange: vi.fn(),
      onSearchSpaces: vi.fn(),
    }
    const { rerender } = render(
      <DeveloperTokenFileSyncTargetTree {...props} userId={7} />
    )
    fireEvent.click(screen.getByRole("button", { name: "Safety" }))
    await waitFor(() => expect(mockedChildren).toHaveBeenCalledTimes(1))

    rerender(<DeveloperTokenFileSyncTargetTree {...props} userId={8} />)
    fireEvent.click(screen.getByRole("button", { name: "Safety" }))
    await waitFor(() => expect(screen.getByText("New user folder")).toBeInTheDocument())
    resolveOld({
      data: [{
        id: 4000,
        name: "Old user folder",
        selectable: true,
        navigation_only: false,
        has_children: false,
      }],
      has_more: false,
      next_cursor: null,
      page_size: 50,
    })

    await waitFor(() => expect(screen.queryByText("Old user folder")).not.toBeInTheDocument())
  })
})
