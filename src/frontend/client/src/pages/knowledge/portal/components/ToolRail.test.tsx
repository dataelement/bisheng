import { fireEvent, render, screen, within } from "@testing-library/react";
import { ToolRail } from "./ToolRail";

function renderRail(overrides: Partial<Parameters<typeof ToolRail>[0]> = {}) {
    return render(
        <ToolRail
            activePanel={null}
            aiOpen={false}
            onTogglePanel={jest.fn()}
            onOpenAi={jest.fn()}
            onOpenPanel={jest.fn()}
            {...overrides}
        />,
    );
}

describe("ToolRail file correction", () => {
    it("puts the correction button on the right rail, not in the document header", () => {
        const onOpenCorrection = jest.fn();
        renderRail({ showCorrection: true, onOpenCorrection });

        const rail = screen.getByTestId("portal-tool-rail");
        const button = within(rail).getByRole("button", { name: "纠错" });
        fireEvent.click(button);

        expect(onOpenCorrection).toHaveBeenCalledTimes(1);
    });

    it("hides the correction button when the reader cannot submit", () => {
        renderRail({ showCorrection: false });

        expect(within(screen.getByTestId("portal-tool-rail"))
            .queryByRole("button", { name: "纠错" }))
            .not.toBeInTheDocument();
    });

    it("marks the correction button pressed while the drawer is open", () => {
        renderRail({ showCorrection: true, correctionOpen: true });

        expect(within(screen.getByTestId("portal-tool-rail"))
            .getByRole("button", { name: "纠错" }))
            .toHaveAttribute("aria-pressed", "true");
    });
});
