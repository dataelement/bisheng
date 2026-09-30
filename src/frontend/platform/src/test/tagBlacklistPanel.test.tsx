import { TagBlacklistPanel } from "@/pages/BuildPage/bench/standalone/tagConsole/TagBlacklistPanel"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const api = vi.hoisted(() => ({
    add: vi.fn(),
    search: vi.fn(),
    preview: vi.fn(),
    toast: vi.fn(),
    remove: vi.fn(),
    confirm: vi.fn(),
}))

vi.mock("@/controllers/API/knowledgeSpaceTagLibrary", () => ({
    addTagBlacklistApi: api.add,
    searchTagBlacklistApi: api.search,
    previewTagBlacklistApi: api.preview,
    deleteTagBlacklistApi: api.remove,
}))
vi.mock("@/controllers/request", () => ({
    captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise.catch(() => false),
}))
vi.mock("@/components/bs-ui/toast/use-toast", () => ({ useToast: () => ({ toast: api.toast }) }))
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({ bsConfirm: api.confirm }))
vi.mock("@/components/bs-ui/pagination/autoPagination", () => ({
    default: ({ page, onChange, onPageSizeChange }) => <div>
        <span data-testid="page">{page}</span>
        <button onClick={() => onChange(page + 1)}>下一页</button>
        <button onClick={() => onPageSizeChange(50)}>每页50条</button>
    </div>,
}))
vi.mock("@/components/bs-icons/search", () => ({ SearchIcon: () => null }))
vi.mock("react-i18next", () => ({
    useTranslation: () => ({
        t: (key: string, fallback?: string | object, values?: Record<string, unknown>) => typeof fallback === "string"
            ? fallback.replace(/{{(\w+)}}/g, (_, name) => String(values?.[name] ?? `{{${name}}}`)) : key,
    }),
}))

afterEach(cleanup)
beforeEach(() => {
    vi.clearAllMocks()
    api.add.mockReset().mockImplementation(async (name) => ({ id: 1, name }))
    api.search.mockReset().mockResolvedValue({ data: [], count: 0, total: 0, limit: 1000 })
    api.remove.mockReset().mockResolvedValue(true)
    api.preview.mockReset().mockResolvedValue({ count: 0, limit: 1000, new_count: 2, would_exceed: false })
})

describe("blacklist bulk deletion", () => {
    const rows = [1, 2, 3].map((id) => ({ id, name: `标签${id}`, create_time: "2026-09-30 10:00:00" }))
    const response = (data = rows, total = data.length) => ({ data, total, count: total, limit: 1000 })

    async function openList() {
        const user = userEvent.setup()
        render(<TagBlacklistPanel />)
        await screen.findByText("标签1")
        return user
    }

    async function confirmDeletion() {
        const dialog = api.confirm.mock.calls.at(-1)![0]
        await act(async () => { await dialog.onOk(dialog.onClose) })
    }

    it("selects only checked rows and does not delete until confirmation", async () => {
        api.search.mockResolvedValue(response())
        const user = await openList()
        const bulk = screen.getByRole("button", { name: "批量删除" })
        expect(bulk).toBeDisabled()
        await user.click(screen.getByRole("checkbox", { name: "选择 标签1" }))
        expect(screen.getByRole("checkbox", { name: "全选当前页" })).toBePartiallyChecked()
        await user.click(bulk)
        expect(api.confirm.mock.calls[0][0].desc).toContain("1 个标签")
        expect(api.remove).not.toHaveBeenCalled()
        act(() => api.confirm.mock.calls[0][0].onClose())
        expect(api.remove).not.toHaveBeenCalled()
        await user.click(bulk)
        api.search.mockResolvedValue(response(rows.slice(1)))
        await confirmDeletion()
        expect(api.remove.mock.calls).toEqual([[1]])
        expect(bulk).toBeDisabled()
        expect(screen.queryByText("标签1")).not.toBeInTheDocument()
    })

    it.each(["page", "size", "search"])("clears page selection on %s changes", async (change) => {
        api.search.mockResolvedValue(response(rows, 40))
        const user = await openList()
        await user.click(screen.getByRole("checkbox", { name: "全选当前页" }))
        expect(screen.getByText("已选择 3 项")).toBeInTheDocument()
        if (change === "search") {
            await user.type(screen.getByPlaceholderText("搜索黑名单"), "标签")
            await user.click(screen.getByRole("button", { name: "搜索" }))
        } else {
            await user.click(screen.getByRole("button", { name: change === "page" ? "下一页" : "每页50条" }))
        }
        await waitFor(() => expect(api.search).toHaveBeenCalledTimes(2))
        expect(screen.getByRole("button", { name: "批量删除" })).toBeDisabled()
        expect(screen.getByRole("checkbox", { name: "全选当前页" })).not.toBeChecked()
        expect(api.remove).not.toHaveBeenCalled()
    })

    it.each([false, "canceled", "refresh failure"])("retains unfinished selection after %s and retries without successful rows", async (failure) => {
        api.search.mockResolvedValue(response())
        api.remove.mockResolvedValueOnce(true).mockResolvedValueOnce(failure === "refresh failure" ? false : failure)
        const user = await openList()
        await user.click(screen.getByRole("checkbox", { name: "全选当前页" }))
        await user.click(screen.getByRole("button", { name: "批量删除" }))
        expect(screen.getByRole("button", { name: "批量删除" })).toBeDisabled()
        expect(screen.getByRole("checkbox", { name: "选择 标签2" })).toBeDisabled()
        api.search.mockResolvedValue(response(rows.slice(1)))
        if (failure === "refresh failure") api.search.mockRejectedValueOnce(new Error("刷新失败"))
        await confirmDeletion()
        expect(api.remove.mock.calls).toEqual([[1], [2]])
        expect(screen.queryByText("标签1")).not.toBeInTheDocument()
        expect(screen.getByText("已选择 2 项")).toBeInTheDocument()
        expect(api.toast).toHaveBeenCalledWith(expect.objectContaining({ variant: "error", description: "已删除 1 条，剩余 2 条未完成，请重试。" }))
        await user.click(screen.getByRole("button", { name: "批量删除" }))
        api.search.mockResolvedValue(response([]))
        await confirmDeletion()
        expect(api.remove.mock.calls).toEqual([[1], [2], [2], [3]])
        expect(screen.getByText("暂无黑名单标签")).toBeInTheDocument()
    })

    it("returns to the previous page when deleting the last row", async () => {
        api.search.mockResolvedValueOnce(response(rows, 21)).mockResolvedValueOnce(response([rows[0]], 21)).mockResolvedValue(response(rows.slice(1), 20))
        const user = await openList()
        await user.click(screen.getByRole("button", { name: "下一页" }))
        await waitFor(() => expect(screen.queryByText("标签2")).not.toBeInTheDocument())
        await user.click(screen.getByRole("button", { name: "移除" }))
        await confirmDeletion()
        expect(api.remove.mock.calls).toEqual([[1]])
        expect(api.search).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }))
        expect(screen.getByTestId("page")).toHaveTextContent("1")
    })
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
