import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import ProgressItem from "@/components/bs-comp/knowledgeUploadComponent/ProgressItem"

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      if (key === "parseQueueStage.title") return "标题提取"
      if (key === "parseQueueStage.parse") return "正式解析"
      if (key === "parseQueueStage.retry") return "重试解析"
      if (key === "parseQueueAhead") return `${values?.stage}排队中，前方约 ${values?.count} 个等待任务`
      if (key === "parseQueueProcessing") return `${values?.stage}处理中`
      if (key === "parseQueueActiveCount") return `当前运行 ${values?.count} 个任务`
      if (key === "parseQueueUnavailable") return "文档数据准备中"
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
  it("shows approximate queued position and independent active count", () => {
    render(
      <ProgressItem
        analysis
        item={{
          ...baseItem,
          queuePosition: {
            state: "queued",
            stage: "title",
            aheadWaitingCount: 7,
            activeCount: 3,
          },
        } as any}
      />,
    )

    expect(screen.getByText(/标题提取排队中，前方约 7 个等待任务/)).toBeInTheDocument()
    expect(screen.getByText(/当前运行 3 个任务/)).toBeInTheDocument()
  })

  it("shows processing and safely degrades unavailable state", () => {
    const { rerender } = render(
      <ProgressItem
        analysis
        item={{
          ...baseItem,
          queuePosition: {
            state: "processing",
            stage: "parse",
            aheadWaitingCount: null,
            activeCount: 1,
          },
        } as any}
      />,
    )
    expect(screen.getByText(/正式解析处理中/)).toBeInTheDocument()

    rerender(
      <ProgressItem
        analysis
        item={{
          ...baseItem,
          queuePosition: {
            state: "unavailable",
            stage: null,
            aheadWaitingCount: null,
            activeCount: 0,
          },
        } as any}
      />,
    )
    expect(screen.getByText("文档数据准备中")).toBeInTheDocument()
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
            stage: "retry",
            aheadWaitingCount: 2,
            activeCount: 1,
          },
        } as any}
      />,
    )
    expect(screen.queryByText(/等待任务|处理中|文档数据准备中/)).not.toBeInTheDocument()
  })
})
