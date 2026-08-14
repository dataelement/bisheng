import { render, screen } from "@testing-library/react";
import { FilePublishTargetTree, normalizePublishTargetLevel } from "./FilePublishTargetTree";

describe("normalizePublishTargetLevel", () => {
    it("maps team_ks clinic spaces into the team/clinic group", () => {
        expect(normalizePublishTargetLevel("team_ks")).toBe("team");
    });

    it("preserves standard publish target levels", () => {
        expect(normalizePublishTargetLevel("team")).toBe("team");
        expect(normalizePublishTargetLevel("department")).toBe("department");
    });
});

describe("FilePublishTargetTree", () => {
    it("renders team_ks clinic spaces under the team/clinic group", () => {
        render(
            <FilePublishTargetTree
                loading={false}
                targetSpaces={[
                    {
                        id: 3637,
                        name: "智能制造室(制造)",
                        space_level: "team_ks",
                        can_browse_files: true,
                    },
                    {
                        id: 100,
                        name: "人才培养知识库",
                        space_level: "team",
                        can_browse_files: true,
                    },
                ]}
                targetSpaceId=""
                targetFolderId={null}
                onSelectRoot={() => undefined}
                onSelectFolder={() => undefined}
            />,
        );

        expect(screen.getByRole("button", { name: /团队\/科室知识库分组/ })).toHaveTextContent("(2)");
        expect(screen.getByRole("button", { name: "选择智能制造室(制造)根目录" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "选择人才培养知识库根目录" })).toBeInTheDocument();
    });
});
