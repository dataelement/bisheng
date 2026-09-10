import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import FilterByDate from "@/components/bs-comp/filterTableDataComponent/FilterByDate"
import { ClearableFilterSelect } from "@/pages/LogPage/ClearableFilterSelect"
import AppUseLog from "@/pages/LogPage/useAppLog"
import SystemLog from "@/pages/LogPage/systemLog"

const { filterData } = vi.hoisted(() => ({ filterData: vi.fn() }))
vi.mock("@/components/bs-icons/search/Search.svg?react", () => ({ default: () => <svg /> }))
vi.mock("@/util/hook", () => ({
    useTable: () => ({ page: 1, pageSize: 20, data: [], total: 0, loading: false, setPage: vi.fn(), filterData }),
}))
vi.mock("@/contexts/locationContext", async () => ({
    locationContext: (await import("react")).createContext({ appConfig: { isPro: true } }),
}))
vi.mock("@/contexts/userContext", async () => ({
    userContext: (await import("react")).createContext({ user: { user_name: "admin" } }),
}))
vi.mock("@/routes/standalone", () => ({ useStandalonePrefix: () => "" }))
vi.mock("@/controllers/API/user", () => ({
    getUserGroupsApi: async () => [{ id: "group-1", group_name: "测试用户组" }],
    getUsersApi: async () => ({ data: [{ user_id: "user-1", user_name: "测试用户", external_id: "001" }] }),
}))
vi.mock("@/controllers/API/log", () => ({
    getGroupsApi: async () => ({ data: [] }),
    getOperatorsApi: async () => [{ user_id: "user-1", user_name: "测试用户" }],
    getResponsiblePersonsApi: async () => [{ user_id: "owner-1", user_name: "测试责任人" }],
    getModulesApi: async () => ({ data: [{ value: "module-1", name: "测试模块" }] }),
    getActionsApi: async () => [{ value: "action-1", name: "测试操作" }],
    getActionsByModuleApi: async () => [{ value: "action-1", name: "测试操作" }],
    getLogsApi: vi.fn(), getAuditAppListApi: vi.fn(), exportCsvDataApi: vi.fn(),
}))

beforeAll(() => {
    window.PointerEvent ||= MouseEvent as typeof PointerEvent
    Element.prototype.hasPointerCapture ||= () => false
    Element.prototype.setPointerCapture ||= vi.fn()
    Element.prototype.releasePointerCapture ||= vi.fn()
    Element.prototype.scrollIntoView ||= vi.fn()
    vi.stubGlobal("IntersectionObserver", class {
        observe() {} unobserve() {} disconnect() {}
    })
})
afterEach(() => { cleanup(); vi.clearAllMocks() })

function filterTrigger(placeholder: string) {
    return screen.getAllByRole("combobox").find((element) => element.textContent === placeholder)!
}

async function pickFilter(placeholder: string, label: string) {
    fireEvent.keyDown(filterTrigger(placeholder), { key: "ArrowDown" })
    const option = await screen.findByText(label, { exact: true })
    await userEvent.click(option)
    fireEvent.keyDown(document.activeElement!, { key: "Escape" })
}

describe("审计筛选清除", () => {
    it.each(["click", "Enter", " "])("单选通过 %s 清空并恢复占位，不打开菜单", async (method) => {
        function Harness() {
            const [value, setValue] = useState("like")
            return <ClearableFilterSelect value={value} placeholder="用户反馈"
                options={[{ value: "like", label: "点赞" }]} onValueChange={setValue} />
        }
        render(<Harness />)
        const clear = screen.getByRole("button", { name: /用户反馈/ })
        if (method === "click") await userEvent.click(clear)
        else { clear.focus(); await userEvent.keyboard(method === "Enter" ? "{Enter}" : " ") }
        expect(screen.queryByRole("button", { name: /用户反馈/ })).not.toBeInTheDocument()
        expect(screen.getByRole("combobox")).toHaveTextContent("用户反馈")
        expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "false")
    })

    it.each([0, 1])("清空第 %s 个日期只移除当前边界", async (index) => {
        const dates: [Date, Date] = [new Date(2026, 8, 1), new Date(2026, 8, 10)]
        const onChange = vi.fn()
        function Harness() {
            const [value, setValue] = useState<[Date | null, Date | null]>(dates)
            return <FilterByDate value={value} placeholders={["开始日期", "结束日期"]}
                onChange={(next) => { onChange(next); setValue(next) }} />
        }
        render(<Harness />)
        await userEvent.click(screen.getByRole("button", { name: new RegExp(index ? "结束日期" : "开始日期") }))
        expect(onChange).toHaveBeenLastCalledWith(index ? [dates[0], null] : [null, dates[1]])
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
        expect(screen.getByText(index ? "结束日期" : "开始日期")).toBeInTheDocument()
    })

    it("应用使用：用户名、用户组、反馈和敏感审核均可清除，查询收到空值", async () => {
        render(<MemoryRouter><AppUseLog /></MemoryRouter>)
        await waitFor(() => expect(filterTrigger("log.userGroup")).not.toBeDisabled())
        for (const [placeholder, label] of [
            ["log.userName", "测试用户 (001)"], ["log.userGroup", "测试用户组"],
            ["log.userFeedbackPlaceholder", "log.likeFeedback"], ["log.sensitiveReviewResult", "log.sensitiveViolation"],
        ]) {
            await pickFilter(placeholder, label)
            const clear = screen.getByRole("button", { name: new RegExp(placeholder) })
            await userEvent.click(clear)
            expect(screen.queryByRole("button", { name: new RegExp(placeholder) })).not.toBeInTheDocument()
        }
        await userEvent.click(screen.getByRole("button", { name: "log.searchButton" }))
        expect(filterData).toHaveBeenLastCalledWith(expect.objectContaining({ userName: [], userGroup: "", feedback: "", sensitive_status: "" }))
    })

    it("系统操作：清空人员和用户组；清空模块同时清空关联操作", async () => {
        render(<SystemLog />)
        for (const [placeholder, label] of [
            ["log.selectUser", "测试用户"], ["log.selectResponsiblePerson", "测试责任人"],
            ["log.selectUserGroup", "测试用户组"],
        ]) {
            await pickFilter(placeholder, label)
            await userEvent.click(screen.getByRole("button", { name: new RegExp(placeholder) }))
        }
        await pickFilter("log.systemModule", "测试模块")
        await pickFilter("log.actionBehavior", "测试操作")
        expect(screen.getByRole("button", { name: /log.actionBehavior/ })).toBeInTheDocument()
        await userEvent.click(screen.getByRole("button", { name: /log.systemModule/ }))
        expect(screen.queryByRole("button", { name: /log.actionBehavior/ })).not.toBeInTheDocument()
        await userEvent.click(screen.getByRole("button", { name: "log.searchButton" }))
        expect(filterData).toHaveBeenLastCalledWith(expect.objectContaining({ userIds: [], responsibleUserIds: [], groupId: "", moduleId: "", action: "" }))
    })
})
