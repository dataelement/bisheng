import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import ProgressItem from "@/components/bs-comp/knowledgeUploadComponent/ProgressItem"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      if (key === "parseQueueAhead") return `排队中，前方约 ${values?.count} 个等待任务`
      if (key === "parseQueueProcessing") return "解析中"
      if (key === "parseQueueUnavailable") return "排队中"
      return key
    },
  }),
}))

vi.mock("@/components/bs-icons/file", () => ({ FileIcon: () => <span>file</span> }))

const baseItem = {
  id: "1",
  fileName: "guide.pdf",
  progress: "await",
  error: false,
  reason: "",
}

describe("parse queue position", () => {
  it("shows only the generic approximate queued position", () => {
    render(
      <ProgressItem
        analysis
        item={{
          ...baseItem,
          queuePosition: {
            state: "queued",
            aheadWaitingCount: 7,
            activeCount: 3,
          },
        } as any}
      />,
    )

    expect(screen.getByText("排队中，前方约 7 个等待任务")).toBeInTheDocument()
    expect(screen.queryByText(/标题提取|正式解析|重试解析|当前运行/)).not.toBeInTheDocument()
  })

  it("shows processing and safely degrades unavailable state", () => {
    const { rerender } = render(
      <ProgressItem
        analysis
        item={{
          ...baseItem,
          queuePosition: {
            state: "processing",
            aheadWaitingCount: null,
            activeCount: 1,
          },
        } as any}
      />,
    )
    expect(screen.getByText("解析中")).toBeInTheDocument()

    rerender(
      <ProgressItem
        analysis
        item={{
          ...baseItem,
          queuePosition: {
            state: "unavailable",
            aheadWaitingCount: null,
            activeCount: 0,
          },
        } as any}
      />,
    )
    expect(screen.getByText("排队中")).toBeInTheDocument()
  })

  it("stops showing queue information for terminal files", () => {
    render(
      <ProgressItem
        analysis
        item={{
          ...baseItem,
          progress: "end",
          queuePosition: {
            state: "queued",
            aheadWaitingCount: 2,
            activeCount: 1,
          },
        } as any}
      />,
    )
    expect(screen.queryByText(/等待任务|解析中|排队中/)).not.toBeInTheDocument()
  })
})
