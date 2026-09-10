import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/bs-ui/dropdownMenu"
import { MultiSelect } from "@/components/bs-ui/multiSelect.tsx"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest"

let activeFullscreenElement: Element | null = null
let originalFullscreenDescriptor: PropertyDescriptor | undefined

function createFullscreenRoot(): HTMLDivElement {
  const root = document.createElement("div")
  document.body.appendChild(root)
  return root
}

function setFullscreenElement(element: Element | null) {
  activeFullscreenElement = element
  act(() => {
    document.dispatchEvent(new Event("fullscreenchange"))
  })
}

beforeAll(() => {
  originalFullscreenDescriptor = Object.getOwnPropertyDescriptor(document, "fullscreenElement")
  Object.defineProperty(document, "fullscreenElement", {
    configurable: true,
    get: () => activeFullscreenElement,
  })

  if (!window.PointerEvent) {
    Object.defineProperty(window, "PointerEvent", {
      configurable: true,
      value: MouseEvent,
    })
  }

  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = vi.fn()
  }

  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = vi.fn(() => false)
  }

  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = vi.fn()
  }

  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = vi.fn()
  }
})

afterEach(() => {
  activeFullscreenElement = null
  cleanup()
  document.body.innerHTML = ""
})

afterAll(() => {
  if (originalFullscreenDescriptor) {
    Object.defineProperty(document, "fullscreenElement", originalFullscreenDescriptor)
  } else {
    delete (document as Document & { fullscreenElement?: Element | null }).fullscreenElement
  }
})

describe("fullscreen overlay portals", () => {
  it("mounts dashboard MultiSelect content inside the active fullscreen element", async () => {
    const fullscreenRoot = createFullscreenRoot()
    render(
      <MultiSelect
        aria-label="Department filter"
        options={[{ label: "Department A", value: "department-a" }]}
        onSearch={() => {}}
      />,
      { container: fullscreenRoot },
    )

    setFullscreenElement(fullscreenRoot)
    fireEvent.click(screen.getByRole("combobox", { name: "Department filter" }))

    const option = await screen.findByRole("option", { name: "Department A" })
    expect(fullscreenRoot).toContainElement(option)
  })

  it("moves Popover content with fullscreen state and restores the default body portal", async () => {
    const fullscreenRoot = createFullscreenRoot()
    render(
      <Popover>
        <PopoverTrigger>Open date picker</PopoverTrigger>
        <PopoverContent data-testid="date-picker-content">Date picker</PopoverContent>
      </Popover>,
      { container: fullscreenRoot },
    )

    setFullscreenElement(fullscreenRoot)
    fireEvent.click(screen.getByRole("button", { name: "Open date picker" }))

    const content = await screen.findByTestId("date-picker-content")
    expect(fullscreenRoot).toContainElement(content)

    setFullscreenElement(null)
    await waitFor(() => {
      const restoredContent = screen.getByTestId("date-picker-content")
      expect(fullscreenRoot).not.toContainElement(restoredContent)
      expect(document.body).toContainElement(restoredContent)
    })
  })

  it("mounts Select and DropdownMenu content inside the active fullscreen element", async () => {
    const fullscreenRoot = createFullscreenRoot()
    render(
      <>
        <Select>
          <SelectTrigger aria-label="Dataset">
            <SelectValue placeholder="Select dataset" />
          </SelectTrigger>
          <SelectContent data-testid="select-content">
            <SelectItem value="dataset-a">Dataset A</SelectItem>
          </SelectContent>
        </Select>
        <DropdownMenu>
          <DropdownMenuTrigger>Open component menu</DropdownMenuTrigger>
          <DropdownMenuContent data-testid="menu-content">
            <DropdownMenuItem>Export</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </>,
      { container: fullscreenRoot },
    )

    setFullscreenElement(fullscreenRoot)

    const selectTrigger = screen.getByRole("combobox", { name: "Dataset" })
    selectTrigger.focus()
    fireEvent.keyDown(selectTrigger, { key: "ArrowDown", code: "ArrowDown", keyCode: 40 })
    expect(fullscreenRoot).toContainElement(await screen.findByTestId("select-content"))

    fireEvent.keyDown(selectTrigger, { key: "Escape", code: "Escape", keyCode: 27 })
    fireEvent.pointerDown(screen.getByRole("button", { name: "Open component menu" }), {
      button: 0,
      ctrlKey: false,
    })
    expect(fullscreenRoot).toContainElement(await screen.findByTestId("menu-content"))
  })

  it("keeps an explicit Popover portal container ahead of the fullscreen element", async () => {
    const fullscreenRoot = createFullscreenRoot()
    const mountRoot = document.createElement("div")
    const explicitRoot = document.createElement("div")
    fullscreenRoot.appendChild(mountRoot)
    fullscreenRoot.appendChild(explicitRoot)
    render(
      <Popover>
        <PopoverTrigger>Open explicit popover</PopoverTrigger>
        <PopoverContent portalContainer={explicitRoot} data-testid="explicit-content">
          Explicit content
        </PopoverContent>
      </Popover>,
      { container: mountRoot },
    )

    setFullscreenElement(fullscreenRoot)
    fireEvent.click(screen.getByRole("button", { name: "Open explicit popover" }))

    expect(explicitRoot).toContainElement(await screen.findByTestId("explicit-content"))
  })
})
