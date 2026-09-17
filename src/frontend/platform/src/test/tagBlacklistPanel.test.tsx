import { TagBlacklistPanel } from "@/pages/BuildPage/bench/standalone/tagConsole/TagBlacklistPanel"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const api = vi.hoisted(() => ({
    add: vi.fn(),
    search: vi.fn(),
    preview: vi.fn(),
    toast: vi.fn(),
}))

vi.mock("@/controllers/API/knowledgeSpaceTagLibrary", () => ({
    addTagBlacklistApi: api.add,
    searchTagBlacklistApi: api.search,
    previewTagBlacklistApi: api.preview,
    deleteTagBlacklistApi: vi.fn(),
}))
vi.mock("@/controllers/request", () => ({
    captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise.catch(() => false),
}))
vi.mock("@/components/bs-ui/toast/use-toast", () => ({ useToast: () => ({ toast: api.toast }) }))
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: vi.fn() }))
vi.mock("@/components/bs-ui/pagination/autoPagination", () => ({ default: () => null }))
vi.mock("@/components/bs-icons/search", () => ({ SearchIcon: () => null }))
vi.mock("react-i18next", () => ({
    useTranslation: () => ({
        t: (key: string, fallback?: string | object) => typeof fallback === "string" ? fallback : key,
    }),
}))

afterEach(cleanup)
beforeEach(() => {
    vi.clearAllMocks()
    api.add.mockReset().mockImplementation(async (name) => ({ id: 1, name }))
    api.search.mockResolvedValue({ data: [], count: 0, total: 0, limit: 1000 })
    api.preview.mockReset().mockResolvedValue({ count: 0, limit: 1000, new_count: 2, would_exceed: false })
})

async function openDialog() {
    const user = userEvent.setup()
    render(<TagBlacklistPanel />)
    await user.click(screen.getByRole("button", { name: "添加" }))
    const dialog = within(screen.getByRole("dialog"))
    return { user, input: dialog.getByRole("textbox"), confirm: dialog.getByRole("button", { name: "confirm" }) }
}

describe("blacklist multiline entry", () => {
    it("Enter inserts a newline and confirmation saves distinct nonempty lines separately", async () => {
        const { user, input, confirm } = await openDialog()
        expect(input.tagName).toBe("TEXTAREA")
        await user.type(input, "标签甲{Enter}标签乙")
        expect(input).toHaveValue("标签甲\n标签乙")
        expect(api.add).not.toHaveBeenCalled()

        const longName = "字".repeat(64)
        fireEvent.change(input, { target: { value: ` 标签甲 \r\n\r\n${longName}\r\n标签甲\n 标签乙 ` } })
        await user.click(confirm)

        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
        expect(api.preview).toHaveBeenCalledWith(["标签甲", longName, "标签乙"])
        expect(api.add.mock.calls).toEqual([["标签甲"], [longName], ["标签乙"]])
        expect(api.search).toHaveBeenCalledTimes(2)
    })

    it("blocks blank content and labels longer than 64 characters without truncating pasted text", async () => {
        const { input, confirm } = await openDialog()
        fireEvent.change(input, { target: { value: " \n\n " } })
        expect(confirm).toBeDisabled()
        const value = `合法标签\n${"字".repeat(65)}`
        fireEvent.change(input, { target: { value } })
        expect(input).toHaveValue(value)
        expect(screen.getByRole("alert")).toHaveTextContent("超过 64")
        expect(confirm).toBeDisabled()
        expect(api.add).not.toHaveBeenCalled()
    })

    it("retains only unfinished entries after failure and retries without resubmitting saved entries", async () => {
        api.add.mockResolvedValueOnce({ id: 1, name: "标签甲" }).mockRejectedValueOnce(new Error("保存失败"))
        const { user, input, confirm } = await openDialog()
        fireEvent.change(input, { target: { value: "标签甲\n标签乙\n标签丙" } })
        await user.click(confirm)
        await waitFor(() => expect(input).toHaveValue("标签乙\n标签丙"))
        expect(api.search).toHaveBeenCalledTimes(2)
        expect(api.add.mock.calls).toEqual([["标签甲"], ["标签乙"]])
        await user.click(confirm)
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
        expect(api.add.mock.calls).toEqual([["标签甲"], ["标签乙"], ["标签乙"], ["标签丙"]])
    })

    it.each(["capacity", "request"])("keeps all entries without writing when preview fails: %s", async (failure) => {
        if (failure === "capacity") {
            api.preview.mockResolvedValue({ count: 999, limit: 1000, new_count: 2, would_exceed: true })
        } else {
            api.preview.mockRejectedValue(new Error("预检查失败"))
        }
        const { user, input, confirm } = await openDialog()
        fireEvent.change(input, { target: { value: "标签甲\n标签乙" } })
        await user.click(confirm)
        await waitFor(() => expect(confirm).not.toBeDisabled())
        expect(input).toHaveValue("标签甲\n标签乙")
        expect(api.add).not.toHaveBeenCalled()
    })
})
