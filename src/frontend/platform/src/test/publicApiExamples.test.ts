import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { createInstance } from "i18next"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { createElement, type ReactNode } from "react"
import { I18nextProvider } from "react-i18next"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ApiAccess } from "@/components/bs-comp/apiComponent/ApiAccess"
import { ApiAccessFlow } from "@/components/bs-comp/apiComponent/ApiAccessFlow"

vi.unmock("react-i18next")
vi.mock("react-syntax-highlighter", () => ({
  Prism: ({ children }: { children: ReactNode }) => createElement("pre", {}, children),
}))
vi.mock("@/utils", () => ({ copyText: vi.fn().mockResolvedValue(undefined) }))
vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ message: vi.fn() }),
}))

afterEach(cleanup)

const applicationId = "816acf819f254de68cf34779a7586621"

async function renderDocumentation(component: typeof ApiAccess, language = "zh-Hans") {
  const locale = JSON.parse(readFileSync(
    join(process.cwd(), "public", "locales", language, "bs.json"), "utf8",
  ))
  const i18n = createInstance()
  await i18n.init({
    lng: language,
    defaultNS: "bs",
    resources: { [language]: { bs: locale } },
    interpolation: { escapeValue: false },
  })
  return render(createElement(I18nextProvider, { i18n },
    createElement(MemoryRouter, { initialEntries: [`/publish/${applicationId}`] },
      createElement(Routes, {},
        createElement(Route, { path: "/publish/:id", element: createElement(component) }),
      ),
    ),
  ))
}

describe("published API documentation", () => {
  it.each(["zh-Hans", "en-US", "ja"])("restores the complete v2 workflow reference in %s", async (language) => {
    const { container } = await renderDocumentation(ApiAccessFlow, language)
    const text = container.textContent ?? ""
    expect(text).toContain("/api/v2/workflow/invoke")
    expect(text).toContain("/api/v2/workflow/stop")
    expect(text).not.toContain("/api/v3/")
    expect(text).not.toContain("api.workflowDoc.")
    expect(text).toContain(`"workflow_id": "${applicationId}"`)
    expect(text).not.toContain("{{workflowId}}")
    expect(text).toContain(`${location.origin}/api/v2/workflow/invoke`)

    // Preserve the full protocol reference that was lost in the shortened page.
    for (const id of ["guide-t1", "guide-t2", "guide-t3", "guide-1", "guide-2", "guide-3", "guide-5", "guide-6", "guide-7", "guide-8", "guide-9", "guide-10", "guide-11"]) {
      expect(container.querySelector(`#${id}`)).toBeInTheDocument()
    }
    for (const event of ["guide_word", "guide_question", "input", "output_msg", "output_with_input_msg", "output_with_choose_msg", "stream_msg", "close"]) {
      expect(text).toContain(`"event": "${event}"`)
    }
    for (const field of ["session_id", "message_id", "node_execution_id", "input_schema", "output_schema", "reasoning_content", "output_key"]) {
      expect(text).toContain(field)
    }
    expect(text).toContain("/api/v1/knowledge/upload")
    expect(text).toContain("10527")
    expect(text).toContain("10528")
    expect(text).toContain("10531")
  })

  it("shows v2 assistant cURL and Python examples using the current assistant ID", async () => {
    const { container } = await renderDocumentation(ApiAccess)
    expect(container.textContent).toContain("/api/v2/assistant/chat/completions")
    expect(container.textContent).toContain(`"model": "${applicationId}"`)
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Python API" }), { button: 0, ctrlKey: false })
    expect(container.textContent).toContain(`${location.origin}/api/v2/assistant`)
    expect(container.textContent).toContain(`model = "${applicationId}"`)
    expect(container.textContent).not.toContain("/api/v3/")
  })

  it("keeps service-account key examples on authenticated v2", () => {
    const keyReveal = readFileSync(join(process.cwd(), "src",
      "pages/SystemPage/components/ServiceAccount/KeyRevealDialog.tsx",
    ), "utf8")
    expect(keyReveal).toContain("/api/v2/auth/whoami")
    expect(keyReveal).toContain("Authorization: Bearer")
  })
})
