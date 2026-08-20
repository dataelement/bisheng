import { act, cleanup, render } from "@testing-library/react"
import { useRef } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useAutoScrollToNewComponent } from "../pages/Dashboard/components/editor/useAutoScrollToNewComponent"

interface TestCanvasProps {
  componentIds: string[]
}

const TestCanvas = ({ componentIds }: TestCanvasProps) => {
  const scrollContainerRef = useRef<HTMLDivElement>(null)

  useAutoScrollToNewComponent({
    componentIds,
    dashboardId: "dashboard-1",
    enabled: true,
    scrollContainerRef,
  })

  return (
    <div ref={scrollContainerRef}>
      {componentIds.map(componentId => (
        <div key={componentId} data-dashboard-component-id={componentId} />
      ))}
    </div>
  )
}

const originalScrollIntoViewDescriptor = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "scrollIntoView",
)
const originalScrollToDescriptor = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "scrollTo",
)

const restoreElementMethod = (
  method: "scrollIntoView" | "scrollTo",
  descriptor?: PropertyDescriptor,
) => {
  if (descriptor) {
    Object.defineProperty(HTMLElement.prototype, method, descriptor)
  } else {
    delete (HTMLElement.prototype as Partial<HTMLElement>)[method]
  }
}

describe("dashboard component auto scroll", () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    restoreElementMethod("scrollIntoView", originalScrollIntoViewDescriptor)
    restoreElementMethod("scrollTo", originalScrollToDescriptor)
  })

  it("waits for the new grid item to have a stable layout before centering it", () => {
    const animationFrames: FrameRequestCallback[] = []
    const scrollIntoView = vi.fn()
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
      animationFrames.push(callback)
      return animationFrames.length
    }))
    vi.stubGlobal("cancelAnimationFrame", vi.fn())
    Object.defineProperties(HTMLElement.prototype, {
      scrollIntoView: { configurable: true, value: scrollIntoView },
      scrollTo: { configurable: true, value: vi.fn() },
    })

    const { container, rerender } = render(
      <TestCanvas componentIds={["existing-component"]} />,
    )
    expect(requestAnimationFrame).not.toHaveBeenCalled()

    rerender(
      <TestCanvas componentIds={["existing-component", "new-component"]} />,
    )
    const newComponent = container.querySelector<HTMLElement>(
      '[data-dashboard-component-id="new-component"]',
    )!
    let componentRect = {
      top: 0,
      left: 0,
      width: 0,
      height: 0,
    } as DOMRect
    newComponent.getBoundingClientRect = vi.fn(() => componentRect)

    act(() => animationFrames.shift()?.(0))
    expect(scrollIntoView).not.toHaveBeenCalled()
    expect(requestAnimationFrame).toHaveBeenCalledTimes(2)

    componentRect = {
      top: 800,
      left: 20,
      width: 400,
      height: 240,
    } as DOMRect
    act(() => animationFrames.shift()?.(16))
    expect(scrollIntoView).not.toHaveBeenCalled()

    act(() => animationFrames.shift()?.(32))
    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "center",
      inline: "center",
    })
  })
})
