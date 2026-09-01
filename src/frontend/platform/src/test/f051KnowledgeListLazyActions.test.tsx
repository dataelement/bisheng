import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { userContext } from "@/contexts/userContext"

const testState = vi.hoisted(() => ({
  resourceId: "file-knowledge",
  secondResourceId: null as string | null,
  state: 1,
}))

const permissionApi = vi.hoisted(() => vi.fn())
const permissionError = vi.hoisted(() => vi.fn())

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { loadNamespaces: vi.fn() },
  }),
}))

vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: permissionApi,
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: permissionError,
  useToast: () => ({ toast: permissionError, message: permissionError }),
}))

vi.mock("@/components/bs-icons/knowledge", () => ({
  BookIcon: () => <span data-testid="book-icon" />,
  QaIcon: () => <span data-testid="qa-icon" />,
}))

vi.mock("@/components/bs-icons/loading", () => ({
  LoadIcon: () => <span data-testid="load-icon" />,
  LoadingIcon: () => <span data-testid="loading-icon" />,
}))

vi.mock("@/components/bs-ui/input", async () => {
  const React = await import("react")
  const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
    (props, ref) => <input ref={ref} {...props} />,
  )
  const SearchInput = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
    (props, ref) => <input ref={ref} {...props} />,
  )
  const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
    (props, ref) => <textarea ref={ref} {...props} />,
  )
  return { Input, SearchInput, Textarea }
})

vi.mock("@/util/hook", () => ({
  useInfiniteCursorTable: () => ({
    data: [testState.resourceId, testState.secondResourceId]
      .filter((resourceId): resourceId is string => Boolean(resourceId))
      .map((resourceId) => ({
      id: resourceId,
      name: "Knowledge",
      description: "Description",
      state: testState.state,
      actions: ["visible"],
      update_time: "2026-08-25T10:00:00",
      create_time: "2026-08-25T10:00:00",
      user_name: "Owner",
      model: "model-1",
    })),
    loading: false,
    hasMore: false,
    search: vi.fn(),
    reload: vi.fn(),
    loadMore: vi.fn(),
  }),
}))

vi.mock("@/pages/ModelPage/manage", () => ({
  useModel: () => ({ embeddings: [], isLoading: false }),
}))

vi.mock("@/components/bs-ui/select", async () => {
  const React = await import("react")
  interface SelectContextValue {
    open: boolean
    onOpenChange: (open: boolean) => void
    onValueChange: (value: string) => void
  }
  const SelectContext = React.createContext<SelectContextValue | null>(null)

  function Select({ children, open, onOpenChange, onValueChange }: {
    children: ReactNode
    open: boolean
    onOpenChange: (open: boolean) => void
    onValueChange: (value: string) => void
  }) {
    return (
      <SelectContext.Provider value={{ open, onOpenChange, onValueChange }}>
        {children}
        <button
          type="button"
          data-testid="row-actions-close"
          onClick={(event) => {
            event.stopPropagation()
            onOpenChange(false)
          }}
        >
          close
        </button>
      </SelectContext.Provider>
    )
  }

  function SelectTrigger({ children, disabled, onClick }: {
    children: ReactNode
    disabled?: boolean
    onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void
  }) {
    const context = React.useContext(SelectContext)
    return (
      <button
        type="button"
        data-testid="row-actions-trigger"
        disabled={disabled}
        onClick={(event) => {
          onClick?.(event)
          context?.onOpenChange(!context.open)
        }}
      >
        {children}
      </button>
    )
  }

  function SelectContent({ children }: { children: ReactNode }) {
    const context = React.useContext(SelectContext)
    return context?.open ? <div data-testid="row-actions-menu">{children}</div> : null
  }

  function SelectItem({ children, value, disabled }: {
    children: ReactNode
    value: string
    disabled?: boolean
  }) {
    const context = React.useContext(SelectContext)
    return (
      <button
        type="button"
        data-value={value}
        disabled={disabled}
        onClick={() => context?.onValueChange(value)}
      >
        {children}
      </button>
    )
  }

  return { Select, SelectContent, SelectItem, SelectTrigger }
})

import KnowledgeFile from "@/pages/KnowledgePage/KnowledgeFile"
import KnowledgeQa from "@/pages/KnowledgePage/KnowledgeQa"

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function renderPage(page: ReactNode, webMenu: string[] = []) {
  return render(
    <MemoryRouter>
      <userContext.Provider value={{
        user: { user_id: 841, role: "", web_menu: webMenu },
      } as never}>
        {page}
      </userContext.Provider>
    </MemoryRouter>,
  )
}

describe.each([
  ["document knowledge", <KnowledgeFile />, "file-knowledge"],
  ["QA knowledge", <KnowledgeQa />, "qa-knowledge"],
])("F051 lazy row actions: %s", (_label, page, resourceId) => {
  beforeEach(() => {
    testState.resourceId = resourceId
    testState.secondResourceId = null
    testState.state = 1
    permissionApi.mockReset()
    permissionError.mockReset()
  })

  afterEach(cleanup)

  it("keeps the trigger visible and loads only after the menu opens", async () => {
    const request = deferred<{ actions: string[] }>()
    permissionApi.mockReturnValue(request.promise)
    renderPage(page)

    expect(permissionApi).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId("row-actions-trigger"))

    expect(permissionApi).toHaveBeenCalledTimes(1)
    expect(permissionApi).toHaveBeenCalledWith("knowledge_library", resourceId)
    expect(document.querySelector('[data-value="loading"]')).not.toBeNull()
    expect(document.querySelector('[data-value="set"]')).toBeNull()

    request.resolve({ actions: ["visible", "edit", "manage_permission"] })
    await waitFor(() => {
      expect(document.querySelector('[data-value="set"]')).not.toBeNull()
      expect(document.querySelector('[data-value="permission"]')).not.toBeNull()
    })
    expect(document.querySelector('[data-value="delete"]')).toBeNull()
  })
})

describe("F051 lazy row action failure and busy states", () => {
  beforeEach(() => {
    testState.resourceId = "failure-knowledge"
    testState.secondResourceId = null
    testState.state = 1
    permissionApi.mockReset()
    permissionError.mockReset()
  })

  afterEach(cleanup)

  it("closes the menu and reports a failed permission lookup", async () => {
    permissionApi.mockRejectedValue(new Error("permission unavailable"))
    renderPage(<KnowledgeFile />)

    fireEvent.click(screen.getByTestId("row-actions-trigger"))
    await waitFor(() => expect(permissionError).toHaveBeenCalled())
    expect(screen.queryByTestId("row-actions-menu")).toBeNull()
    expect(document.querySelector('[data-value="set"]')).toBeNull()
  })

  it("does not query actions for a busy row", () => {
    testState.state = 2
    renderPage(<KnowledgeQa />)

    fireEvent.click(screen.getByTestId("row-actions-trigger"))
    expect(permissionApi).not.toHaveBeenCalled()
  })

  it("keeps B open when A emits a late close and never mixes their actions", async () => {
    testState.resourceId = "switch-a"
    testState.secondResourceId = "switch-b"
    const requestA = deferred<{ actions: string[] }>()
    const requestB = deferred<{ actions: string[] }>()
    permissionApi.mockImplementation((_type: string, resourceId: string) =>
      resourceId === "switch-a" ? requestA.promise : requestB.promise)
    renderPage(<KnowledgeFile />)

    const triggers = screen.getAllByTestId("row-actions-trigger")
    const closeButtons = screen.getAllByTestId("row-actions-close")
    fireEvent.click(triggers[0])
    fireEvent.click(triggers[1])
    fireEvent.click(closeButtons[0])
    expect(screen.getByTestId("row-actions-menu")).not.toBeNull()

    requestB.resolve({ actions: ["delete"] })
    await waitFor(() => {
      expect(document.querySelector('[data-value="delete"]')).not.toBeNull()
    })
    await act(async () => requestA.resolve({ actions: ["edit"] }))
    expect(permissionApi).toHaveBeenCalledTimes(2)
    expect(document.querySelector('[data-value="delete"]')).not.toBeNull()
    expect(document.querySelector('[data-value="set"]')).toBeNull()
  })

  it("does not reopen a menu after it is closed while loading", async () => {
    testState.resourceId = "closed-while-loading"
    const request = deferred<{ actions: string[] }>()
    permissionApi.mockReturnValue(request.promise)
    renderPage(<KnowledgeQa />)

    fireEvent.click(screen.getByTestId("row-actions-trigger"))
    fireEvent.click(screen.getByTestId("row-actions-close"))
    request.resolve({ actions: ["edit"] })

    await waitFor(() => expect(permissionApi).toHaveBeenCalledTimes(1))
    expect(screen.queryByTestId("row-actions-menu")).toBeNull()
  })

  it("keeps copy independent from the lazy management actions", async () => {
    testState.resourceId = "copy-only"
    permissionApi.mockResolvedValue({ actions: ["visible"] })
    renderPage(<KnowledgeFile />, ["create_knowledge"])

    fireEvent.click(screen.getByTestId("row-actions-trigger"))
    await waitFor(() => {
      expect(document.querySelector('[data-value="copy"]')).not.toBeNull()
    })
    expect(document.querySelector('[data-value="set"]')).toBeNull()
    expect(document.querySelector('[data-value="delete"]')).toBeNull()
    expect(document.querySelector('[data-value="permission"]')).toBeNull()
  })
})
