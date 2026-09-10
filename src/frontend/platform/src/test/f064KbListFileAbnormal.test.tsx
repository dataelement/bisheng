import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { userContext } from "@/contexts/userContext"

const testState = vi.hoisted(() => ({
  hasAbnormal: true as boolean,
}))

const filterData = vi.hoisted(() => vi.fn())
const navigate = vi.hoisted(() => vi.fn())

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { loadNamespaces: vi.fn() },
  }),
}))

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom")
  return {
    ...actual,
    useNavigate: () => navigate,
  }
})

vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: vi.fn(),
}))

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: vi.fn(),
  useToast: () => ({ toast: vi.fn(), message: vi.fn() }),
}))

vi.mock("@/components/bs-icons/knowledge", () => ({
  BookIcon: () => <span data-testid="book-icon" />,
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

vi.mock("@/components/bs-ui/select/filter", () => ({
  TableHeadEnumFilter: ({ onChange }: { onChange: (value: string) => void }) => (
    <button type="button" data-testid="file-status-filter" onClick={() => onChange("abnormal")}>
      filter
    </button>
  ),
}))

vi.mock("@/util/hook", () => ({
  useInfiniteCursorTable: () => ({
    data: [{
      id: 41,
      name: "Policy KB",
      description: "Description",
      state: 1,
      actions: ["visible"],
      update_time: "2026-09-10T10:00:00",
      create_time: "2026-09-10T10:00:00",
      user_name: "Owner",
      model: "model-1",
      has_abnormal_files: testState.hasAbnormal,
    }],
    loading: false,
    hasMore: false,
    search: vi.fn(),
    reload: vi.fn(),
    loadMore: vi.fn(),
    filterData,
  }),
}))

vi.mock("@/pages/ModelPage/manage", () => ({
  useModel: () => ({ embeddings: [], isLoading: false }),
}))

import KnowledgeFile from "@/pages/KnowledgePage/KnowledgeFile"

function renderPage(page: ReactNode) {
  return render(
    <MemoryRouter>
      <userContext.Provider value={{
        user: { user_id: 841, role: "", web_menu: [] },
      } as never}>
        {page}
      </userContext.Provider>
    </MemoryRouter>,
  )
}

describe("F064 document KB list file abnormal status", () => {
  beforeEach(() => {
    testState.hasAbnormal = true
    filterData.mockReset()
    navigate.mockReset()
  })

  afterEach(cleanup)

  it("shows the abnormal tag when the library has failed files", () => {
    renderPage(<KnowledgeFile />)
    expect(screen.getByText("fileStatusAbnormal")).not.toBeNull()
    expect(screen.getByText("fileStatus")).not.toBeNull()
  })

  it("keeps the file status cell empty when no file is abnormal", () => {
    testState.hasAbnormal = false
    renderPage(<KnowledgeFile />)
    expect(screen.queryByText("fileStatusAbnormal")).toBeNull()
    expect(screen.getByText("fileStatus")).not.toBeNull()
  })

  it("filters the list to abnormal libraries from the column header", () => {
    renderPage(<KnowledgeFile />)
    fireEvent.click(screen.getByTestId("file-status-filter"))
    expect(filterData).toHaveBeenCalledWith({ has_abnormal: true })
  })

  it("opens an abnormal library with the inner-list prefilter", () => {
    renderPage(<KnowledgeFile />)
    fireEvent.click(screen.getByText("Policy KB"))
    expect(navigate).toHaveBeenCalledWith("/filelib/41?fileStatus=abnormal")
  })

  it("opens a healthy library without the prefilter", () => {
    testState.hasAbnormal = false
    renderPage(<KnowledgeFile />)
    fireEvent.click(screen.getByText("Policy KB"))
    expect(navigate).toHaveBeenCalledWith("/filelib/41")
  })
})
