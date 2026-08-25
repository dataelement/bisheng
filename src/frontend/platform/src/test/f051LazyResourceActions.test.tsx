import {
  useLazyResourceActions,
} from "@/components/bs-comp/permission/useResourceActions"
import { userContext } from "@/contexts/userContext"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

const getMyResourcePermissionsApi = vi.fn()

vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: (...args: unknown[]) =>
    getMyResourcePermissionsApi(...args),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
}))

function Probe() {
  const { actions, errors, loading, load } = useLazyResourceActions(
    "knowledge_library",
    ["edit", "delete", "manage_permission"],
  )

  return (
    <div>
      <button onClick={() => void load("kb-a")}>load-a</button>
      <button onClick={() => void load("kb-b")}>load-b</button>
      <span data-testid="a-actions">{(actions["kb-a"] ?? []).join(",")}</span>
      <span data-testid="b-actions">{(actions["kb-b"] ?? []).join(",")}</span>
      <span data-testid="a-loading">{loading["kb-a"] ? "yes" : "no"}</span>
      <span data-testid="a-error">{errors["kb-a"] ? "yes" : "no"}</span>
    </div>
  )
}

function provider(userId: string, role = "user") {
  return function UserProvider({ children }: { children: ReactNode }) {
    return (
      <userContext.Provider value={{
        user: { user_id: userId, role },
        setUser: vi.fn(),
        savedComponents: [],
        addSavedComponent: vi.fn(),
        checkComponentsName: vi.fn(),
        delComponent: vi.fn(),
      }}>
        {children}
      </userContext.Provider>
    )
  }
}

function probeForUser(userId: string) {
  return (
    <userContext.Provider value={{
      user: { user_id: userId, role: "user" },
      setUser: vi.fn(),
      savedComponents: [],
      addSavedComponent: vi.fn(),
      checkComponentsName: vi.fn(),
      delComponent: vi.fn(),
    }}>
      <Probe />
    </userContext.Provider>
  )
}

describe("F051 lazy resource actions", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("does not request actions until load is called", async () => {
    getMyResourcePermissionsApi.mockResolvedValue({
      actions: ["visible", "edit", "use"],
    })
    render(<Probe />, { wrapper: provider("f051-explicit-user") })

    expect(getMyResourcePermissionsApi).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText("load-a"))

    await waitFor(() => {
      expect(getMyResourcePermissionsApi).toHaveBeenCalledWith(
        "knowledge_library",
        "kb-a",
      )
      expect(screen.getByTestId("a-actions")).toHaveTextContent("edit")
    })
    expect(screen.getByTestId("a-actions")).not.toHaveTextContent("visible")
  })

  it("deduplicates an in-flight request and reuses its cached result", async () => {
    let resolveRequest: (value: { actions: string[] }) => void = () => undefined
    getMyResourcePermissionsApi.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve
    }))
    const wrapper = provider("f051-cache-user")
    const first = render(<Probe />, { wrapper })

    fireEvent.click(screen.getByText("load-a"))
    fireEvent.click(screen.getByText("load-a"))
    expect(screen.getByTestId("a-loading")).toHaveTextContent("yes")
    expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(1)
    resolveRequest({ actions: ["edit", "delete"] })
    await waitFor(() => expect(screen.getByTestId("a-loading")).toHaveTextContent("no"))

    first.unmount()
    render(<Probe />, { wrapper })
    fireEvent.click(screen.getByText("load-a"))
    await waitFor(() => expect(screen.getByTestId("a-actions")).toHaveTextContent("edit,delete"))
    expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(1)
  })

  it("keeps results isolated by resource and user", async () => {
    getMyResourcePermissionsApi
      .mockResolvedValueOnce({ actions: ["edit"] })
      .mockResolvedValueOnce({ actions: ["delete"] })
      .mockResolvedValueOnce({ actions: ["manage_permission"] })

    const first = render(<Probe />, { wrapper: provider("f051-user-one") })
    fireEvent.click(screen.getByText("load-a"))
    fireEvent.click(screen.getByText("load-b"))
    await waitFor(() => {
      expect(screen.getByTestId("a-actions")).toHaveTextContent("edit")
      expect(screen.getByTestId("b-actions")).toHaveTextContent("delete")
    })
    first.unmount()

    render(<Probe />, { wrapper: provider("f051-user-two") })
    fireEvent.click(screen.getByText("load-a"))
    await waitFor(() => {
      expect(screen.getByTestId("a-actions")).toHaveTextContent("manage_permission")
    })
    expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(3)
  })

  it("hides the previous user's actions on the first render after a scope change", async () => {
    getMyResourcePermissionsApi.mockResolvedValue({ actions: ["edit"] })
    const view = render(probeForUser("f051-scope-user-one"))

    fireEvent.click(screen.getByText("load-a"))
    await waitFor(() => {
      expect(screen.getByTestId("a-actions")).toHaveTextContent("edit")
    })

    view.rerender(probeForUser("f051-scope-user-two"))
    expect(screen.getByTestId("a-actions")).toBeEmptyDOMElement()
    expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(1)
  })

  it("reports failure without granting actions", async () => {
    getMyResourcePermissionsApi.mockRejectedValue(new Error("unavailable"))
    render(<Probe />, { wrapper: provider("f051-error-user") })

    fireEvent.click(screen.getByText("load-a"))
    await waitFor(() => expect(screen.getByTestId("a-error")).toHaveTextContent("yes"))
    expect(screen.getByTestId("a-actions")).toBeEmptyDOMElement()
  })

  it("queries the server for administrators instead of fabricating actions", async () => {
    getMyResourcePermissionsApi.mockResolvedValue({ actions: ["edit"] })
    render(<Probe />, { wrapper: provider("f051-admin-user", "admin") })

    expect(getMyResourcePermissionsApi).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText("load-a"))
    await waitFor(() => expect(screen.getByTestId("a-actions")).toHaveTextContent("edit"))
    expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(1)
  })
})
