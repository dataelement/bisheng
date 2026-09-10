import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import AppUseLog from "@/pages/LogPage/useAppLog"

const { getAuditAppListApi, getGroupsApi } = vi.hoisted(() => ({
    getAuditAppListApi: vi.fn(), getGroupsApi: vi.fn(),
}))
vi.mock("@/controllers/API/log", () => ({ getAuditAppListApi, getGroupsApi, exportCsvDataApi: vi.fn() }))
vi.mock("@/controllers/API/user", () => ({
    getUserGroupsApi: async () => [{ id: "group-1", group_name: "测试用户组" }],
    getUsersApi: async () => ({ data: [{ user_id: "user-1", user_name: "测试用户" }] }),
}))
vi.mock("@/contexts/locationContext", async () => ({
    locationContext: (await import("react")).createContext({ appConfig: { isPro: true } }),
}))
vi.mock("@/contexts/userContext", async () => ({
    userContext: (await import("react")).createContext({ user: { user_name: "admin" } }),
}))
vi.mock("@/components/bs-icons", () => ({ ThunmbIcon: () => <svg /> }))
vi.mock("@/components/bs-icons/loading", () => ({ LoadingIcon: () => <svg />, LoadIcon: () => <svg /> }))
vi.mock("@/components/bs-icons/search/Search.svg?react", () => ({ default: () => <svg /> }))
vi.mock("@/components/bs-comp/filterTableDataComponent/FilterByDate", () => ({
    default: ({ value, onChange }) => <input aria-label="日期范围" type="checkbox"
        checked={Boolean(value[0])} onChange={() => onChange([new Date(2026, 8, 1), new Date(2026, 8, 10)])} />,
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

async function pick(placeholder: string, label: string) {
    const trigger = screen.getAllByRole("combobox").find((element) => element.textContent === placeholder)!
    fireEvent.keyDown(trigger, { key: "ArrowDown" })
    await userEvent.click(await screen.findByText(label, { exact: true }))
    fireEvent.keyDown(document.activeElement!, { key: "Escape" })
}

describe("应用使用详情返回", () => {
    it.each([["", 1], ["/standalone", 15]] as const)("%s 返回恢复条件和页码，保留未查询的修改", async (prefix, flowType) => {
        getGroupsApi.mockImplementation(async ({ keyword }) => ({
            data: keyword ? [{ id: "app-21", name: "目标应用" }] : [{ id: "app-1", name: "首屏应用" }],
        }))
        getAuditAppListApi.mockResolvedValue({ total: 60, data: [{
            id: "log-1", flow_id: "app-21", flow_name: "会话记录", flow_type: flowType, chat_id: "chat-1",
            user_name: "admin", user_groups: [], create_time: "2026-09-10T10:00:00", sensitive_status: 1,
        }] })
        function Detail() {
            const navigate = useNavigate()
            return <>
                <button onClick={() => navigate(-1)}>返回列表</button>
                <button onClick={() => navigate(`${prefix}/log`)}>重新进入审计</button>
            </>
        }
        render(<MemoryRouter initialEntries={[`${prefix}/log`]}>
            <Routes>
                <Route path={`${prefix}/log`} element={<AppUseLog />} />
                <Route path={`${prefix}/log/chatlog/*`} element={<Detail />} />
            </Routes>
        </MemoryRouter>)
        await screen.findByRole("link", { name: "lib.details" })
        const appTrigger = screen.getAllByRole("combobox").find((element) => element.textContent === "log.appName")!
        await userEvent.click(appTrigger)
        await userEvent.type(screen.getByRole("textbox"), "目标")
        await userEvent.click(await screen.findByRole("option", { name: "目标应用" }))
        fireEvent.keyDown(document.activeElement!, { key: "Escape" })
        await pick("log.userName", "测试用户")
        await pick("log.userGroup", "测试用户组")
        await userEvent.click(screen.getByRole("checkbox", { name: "日期范围" }))
        await pick("log.userFeedbackPlaceholder", "log.likeFeedback")
        await pick("log.sensitiveReviewResult", "log.sensitiveViolation")
        await userEvent.click(screen.getByRole("button", { name: "log.searchButton" }))
        await userEvent.click(screen.getByRole("link", { name: "2", exact: true }))
        const expectedQuery = {
            page: 2, page_size: 20, flow_ids: ["app-21"], user_ids: "user-1", group_ids: "group-1",
            start_date: "2026-09-01 00:00:00", end_date: "2026-09-10 23:59:59", feedback: "like", sensitive_status: "2",
        }
        await waitFor(() => expect(getAuditAppListApi).toHaveBeenLastCalledWith(expectedQuery))
        await pick("log.likeFeedback", "log.dislikeFeedback")
        await userEvent.click(screen.getByRole("link", { name: "lib.details" }))
        const callsBeforeReturn = getAuditAppListApi.mock.calls.length
        await userEvent.click(screen.getByRole("button", { name: "返回列表" }))
        await waitFor(() => expect(getAuditAppListApi.mock.calls.length).toBeGreaterThan(callsBeforeReturn))
        expect(getAuditAppListApi.mock.calls.slice(callsBeforeReturn).map(([query]) => query)).toEqual([expectedQuery])
        expect(screen.getByText("目标应用")).toBeInTheDocument()
        expect(screen.getByText("测试用户")).toBeInTheDocument()
        expect(screen.getByText("测试用户组")).toBeInTheDocument()
        expect(screen.getByText("log.dislikeFeedback")).toBeInTheDocument()
        expect(screen.getByRole("checkbox", { name: "日期范围" })).toBeChecked()
        expect(screen.getByRole("link", { name: "2", exact: true })).toHaveAttribute("aria-current", "page")

        await userEvent.click(screen.getByRole("link", { name: "3", exact: true }))
        await waitFor(() => expect(getAuditAppListApi).toHaveBeenLastCalledWith({ ...expectedQuery, page: 3 }))
        await userEvent.click(screen.getByRole("button", { name: "log.resetButton" }))
        await waitFor(() => expect(getAuditAppListApi).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, feedback: undefined, flow_ids: undefined })))
        await userEvent.click(screen.getByRole("link", { name: "lib.details" }))
        await userEvent.click(screen.getByRole("button", { name: "返回列表" }))
        await screen.findByRole("link", { name: "lib.details" })
        expect(screen.queryByText("目标应用")).not.toBeInTheDocument()
        expect(screen.getByRole("checkbox", { name: "日期范围" })).not.toBeChecked()
        expect(screen.getByRole("link", { name: "1", exact: true })).toHaveAttribute("aria-current", "page")

        await pick("log.userFeedbackPlaceholder", "log.likeFeedback")
        await userEvent.click(screen.getByRole("button", { name: "log.searchButton" }))
        await userEvent.click(screen.getByRole("link", { name: "lib.details" }))
        await userEvent.click(screen.getByRole("button", { name: "重新进入审计" }))
        await screen.findByRole("link", { name: "lib.details" })
        expect(screen.queryByText("log.likeFeedback")).not.toBeInTheDocument()
        expect(getAuditAppListApi).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, feedback: undefined }))
    })
})
