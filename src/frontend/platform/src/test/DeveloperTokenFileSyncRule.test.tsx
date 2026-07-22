import type {
  DeveloperTokenFileSyncOptions,
  DeveloperTokenFileSyncRule as FileSyncRule,
} from "@/controllers/API/developerToken"
import DeveloperTokenFileSyncRuleEditor from "@/pages/SystemPage/components/DeveloperTokenFileSyncRule"
import { fireEvent, render, screen } from "@testing-library/react"
import { useState } from "react"
import { describe, expect, it, vi } from "vitest"

vi.mock("@/components/bs-ui/select", () => ({
  Select: ({
    children,
    name,
    value,
    onValueChange,
  }: {
    children: React.ReactNode
    name?: string
    value?: string
    onValueChange: (value: string) => void
  }) => (
    <select
      aria-label={name}
      value={value || ""}
      onChange={(event) => onValueChange(event.target.value)}
    >
      {children}
    </select>
  ),
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
}))

vi.mock("@/components/bs-ui/switch", () => ({
  Switch: ({
    checked,
    onCheckedChange,
    ...props
  }: {
    checked: boolean
    onCheckedChange: (value: boolean) => void
    "aria-label"?: string
  }) => (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onCheckedChange(!checked)}
      {...props}
    />
  ),
}))

const options: DeveloperTokenFileSyncOptions = {
  tenant_id: 2,
  user_id: 7,
  categories: [
    {
      code: "POLICY",
      label: "Policy",
      children: [{ code: "MGMT_POLICY", label: "Management policy" }],
    },
    {
      code: "NOTICE",
      label: "Notice",
      children: [{ code: "SAFETY_NOTICE", label: "Safety notice" }],
    },
  ],
  business_domains: [{ code: "SAFETY", name: "Safety" }],
  target_space_groups: {
    data: [{
      space_type: "department",
      spaces: [{ id: 118, name: "Safety space", selectable: true, has_children: false }],
    }],
    has_more: false,
    next_cursor: null,
    page_size: 50,
  },
}

const configuredRule: FileSyncRule = {
  category: { code: "POLICY", subcategory_code: "MGMT_POLICY" },
  business_domain: { mode: "fixed", code: "SAFETY" },
  target_space: { mode: "fixed", knowledge_id: 118, folder_id: null },
  dynamic_source: null,
}

function Harness({ initial = null }: { initial?: FileSyncRule | null }) {
  const [value, setValue] = useState<FileSyncRule | null>(initial)
  return (
    <>
      <DeveloperTokenFileSyncRuleEditor
        value={value}
        onChange={setValue}
        options={options}
        loading={false}
        error={null}
        onSearchSpaces={vi.fn()}
      />
      <output data-testid="rule-state">{JSON.stringify(value)}</output>
    </>
  )
}

describe("DeveloperTokenFileSyncRule", () => {
  it("uses null for disabled state and creates an empty complete-shape editor when enabled", () => {
    render(<Harness />)

    expect(screen.getByTestId("rule-state")).toHaveTextContent("null")
    fireEvent.click(screen.getByRole("switch", { name: "system.developerToken.fileSync.enabled" }))

    expect(screen.getByTestId("rule-state")).toHaveTextContent('"category":{"code":""')
  })

  it("clears the child category when its parent changes", () => {
    render(<Harness initial={configuredRule} />)

    fireEvent.change(screen.getByRole("combobox", { name: "file-sync-category" }), {
      target: { value: "NOTICE" },
    })

    expect(screen.getByTestId("rule-state")).toHaveTextContent(
      '"category":{"code":"NOTICE","subcategory_code":""}'
    )
  })

  it("clears fixed values, conditionally shows dynamic source, and clears it again", () => {
    render(<Harness initial={configuredRule} />)

    fireEvent.change(screen.getByRole("combobox", { name: "file-sync-business-mode" }), {
      target: { value: "dynamic" },
    })
    expect(screen.getByTestId("rule-state")).toHaveTextContent(
      '"business_domain":{"mode":"dynamic","code":null}'
    )
    expect(screen.getByRole("combobox", { name: "file-sync-dynamic-source" })).toBeInTheDocument()

    fireEvent.change(screen.getByRole("combobox", { name: "file-sync-dynamic-source" }), {
      target: { value: "department_id" },
    })
    fireEvent.change(screen.getByRole("combobox", { name: "file-sync-business-mode" }), {
      target: { value: "fixed" },
    })
    expect(screen.queryByRole("combobox", { name: "file-sync-dynamic-source" })).not.toBeInTheDocument()
    expect(screen.getByTestId("rule-state")).toHaveTextContent('"dynamic_source":null')
  })

  it("renders loading and error states and delegates knowledge-space search", () => {
    const onSearchSpaces = vi.fn()
    const { rerender } = render(
      <DeveloperTokenFileSyncRuleEditor
        value={configuredRule}
        onChange={vi.fn()}
        options={null}
        loading
        error={null}
        onSearchSpaces={onSearchSpaces}
      />
    )
    expect(screen.getByText("system.developerToken.fileSync.optionsLoading")).toBeInTheDocument()

    rerender(
      <DeveloperTokenFileSyncRuleEditor
        value={configuredRule}
        onChange={vi.fn()}
        options={null}
        loading={false}
        error="failed"
        onSearchSpaces={onSearchSpaces}
      />
    )
    expect(screen.getByText("system.developerToken.fileSync.optionsError")).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "file-sync-category" })).toHaveValue("POLICY")
    expect(screen.getByRole("combobox", { name: "file-sync-business-domain" })).toHaveValue("SAFETY")
    rerender(
      <DeveloperTokenFileSyncRuleEditor
        value={configuredRule}
        onChange={vi.fn()}
        options={options}
        loading={false}
        error={null}
        onSearchSpaces={onSearchSpaces}
      />
    )
    fireEvent.change(screen.getByPlaceholderText("system.developerToken.fileSync.spaceSearchPlaceholder"), {
      target: { value: "safety" },
    })
    fireEvent.click(screen.getByRole("button", { name: "system.developerToken.fileSync.searchSpace" }))
    expect(onSearchSpaces).toHaveBeenCalledWith("safety")
  })

  it("retains and marks stale stored references instead of remapping them", () => {
    const staleRule: FileSyncRule = {
      category: { code: "REMOVED", subcategory_code: "OLD" },
      business_domain: { mode: "fixed", code: "OLD_DOMAIN" },
      target_space: { mode: "fixed", knowledge_id: 999, folder_id: 4096 },
      dynamic_source: null,
    }
    render(
      <DeveloperTokenFileSyncRuleEditor
        value={staleRule}
        onChange={vi.fn()}
        options={options}
        loading={false}
        error={null}
        onSearchSpaces={vi.fn()}
        targetDisplay={{
          knowledge_id: 999,
          knowledge_name: null,
          target_type: "folder",
          folder_id: 4096,
          folder_path: [],
          stale: true,
        }}
      />
    )

    expect(screen.getAllByText("system.developerToken.fileSync.stale")).toHaveLength(2)
    expect(screen.getByText("system.developerToken.fileSync.targetTree.stale")).toBeInTheDocument()
    expect(screen.getByRole("combobox", { name: "file-sync-category" })).toHaveValue("REMOVED")
    expect(screen.getByRole("combobox", { name: "file-sync-business-domain" })).toHaveValue("OLD_DOMAIN")
  })
})
