import { fireEvent, render, screen } from "@testing-library/react";
import { PortalFilePagination } from "./PortalFilePagination";

jest.mock("~/hooks", () => ({ useLocalize: () => (key: string, values: Record<string, unknown> = {}) => {
    const words = jest.requireActual("~/locales/zh-Hans/translation.json").com_knowledge;
    return Object.entries(values).reduce((text, [name, value]) => text.replaceAll(`{{${name}}}`, String(value)), words[key.split(".")[1]] || key);
} }));

it("未知总数只显示已浏览页，首末页正确禁用，旧页可以直接返回", () => {
    const change = jest.fn();
    const view = render(<PortalFilePagination currentPage={1} maxVisitedPage={3} hasMore loading={false} onPageChange={change} />);
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByText("第 1 页，已浏览到第 3 页")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "前往第 3 页" }));
    expect(change).toHaveBeenCalledWith(3);
    view.rerender(<PortalFilePagination currentPage={3} maxVisitedPage={3} hasMore={false} loading={false} onPageChange={change} />);
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(screen.getByText(/已到末页/)).toBeInTheDocument();
    view.rerender(<PortalFilePagination currentPage={5} maxVisitedPage={5} hasMore={false} loading={false} onPageChange={change} />);
    fireEvent.click(screen.getByRole("button", { name: "前往第 2 页" }));
    expect(change).toHaveBeenLastCalledWith(2);
});

it("长历史允许定位已访问页，未访问页和请求期间禁止提交", () => {
    const change = jest.fn();
    const view = render(<PortalFilePagination currentPage={8} maxVisitedPage={20} hasMore loading={false} onPageChange={change} />);
    const input = screen.getByRole("spinbutton", { name: "已访问页码" });
    fireEvent.change(input, { target: { value: "4" } });
    fireEvent.submit(input.closest("form")!);
    expect(change).toHaveBeenCalledWith(4);
    change.mockClear();
    fireEvent.change(input, { target: { value: "21" } });
    fireEvent.submit(input.closest("form")!);
    expect(change).not.toHaveBeenCalled();
    view.rerender(<PortalFilePagination currentPage={8} maxVisitedPage={20} hasMore loading onPageChange={change} />);
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(input).toBeDisabled();
});


it("首次请求失败或仍在加载时不宣称已访问或已到末页", () => {
    const view = render(<PortalFilePagination currentPage={1} maxVisitedPage={0} hasMore={false} loading={false} terminalKnown={false} onPageChange={jest.fn()} />);
    expect(screen.getByText("暂无已访问页")).toBeInTheDocument();
    expect(screen.queryByText(/已到末页/)).toBeNull();
    view.rerender(<PortalFilePagination currentPage={1} maxVisitedPage={1} hasMore={false} loading onPageChange={jest.fn()} />);
    expect(screen.queryByText(/已到末页/)).toBeNull();
});
