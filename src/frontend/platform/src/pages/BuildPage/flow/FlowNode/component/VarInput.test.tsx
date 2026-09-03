import { fireEvent, render } from "@/test/test-utils";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import VarInput from "./VarInput";

vi.mock("../../flowStore", () => ({
    default: () => ({ flow: { nodes: [] } }),
}));

vi.mock("../flowNodeStore", () => ({
    useUpdateVariableState: () => [null],
}));

vi.mock("./SelectVar", async () => {
    const { forwardRef } = await import("react");
    return {
        default: forwardRef<unknown, { children: ReactNode }>(({ children }, _ref) => children),
    };
});

vi.mock("@/components/bs-ui/tooltip/tip", () => ({
    default: ({ children }) => children,
}));

vi.mock("@/components/bs-icons/rbDrag", () => ({
    RbDragIcon: () => null,
}));

describe("VarInput", () => {
    it("normalizes non-breaking spaces when serializing variable input", () => {
        const onChange = vi.fn();
        const { container } = render(
            <VarInput
                nodeId="mcp-node"
                itemKey="query"
                paramItem={{
                    label: "SQL",
                    required: false,
                    varZh: { "code.result": "code/result" },
                }}
                value=""
                onChange={onChange}
            />,
        );
        const input = container.querySelector('[contenteditable="true"]');
        expect(input).not.toBeNull();

        input!.innerHTML =
            'select * from risk_info where name = <span class="textarea-badge" contenteditable="false">code/result</span>&nbsp;limit 2000';
        fireEvent.input(input!);

        expect(onChange).toHaveBeenLastCalledWith(
            "select * from risk_info where name = {{#code.result#}} limit 2000",
        );
    });
});
