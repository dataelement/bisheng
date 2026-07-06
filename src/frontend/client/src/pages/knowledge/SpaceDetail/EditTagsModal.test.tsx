import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EditTagsModal } from "./EditTagsModal";
import {
    getSpaceTagsApi,
    getKnowledgeSpaceReviewTagVisibilityApi,
    addSpaceTagApi,
    updateFileTagsApi,
} from "~/api/knowledge";

import { useToastContext } from "~/Providers";

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

const mockShowToast = jest.fn();

jest.mock("~/Providers", () => ({
    useToastContext: jest.fn(),
}));

jest.mock("@tanstack/react-query", () => ({
    useQueryClient: () => ({ invalidateQueries: jest.fn() }),
}));

jest.mock("~/api/knowledge", () => ({
    getSpaceTagsApi: jest.fn(),
    getKnowledgeSpaceReviewTagVisibilityApi: jest.fn(),
    addSpaceTagApi: jest.fn(),
    updateFileTagsApi: jest.fn(),
    batchUpdateTagsApi: jest.fn(),
    countSpaceNativeTags: (tags: Array<{ business_type?: string; name?: string }>, recommended: Array<{ name?: string }> = []) => {
        const libraryNames = new Set(recommended.map((item) => String(item.name ?? "").trim().toLowerCase()).filter(Boolean));
        return tags.filter((tag) => {
            if (tag.business_type === "tag_library") return false;
            const name = String(tag.name ?? "").trim().toLowerCase();
            return !libraryNames.has(name);
        }).length;
    },
    countBoundLibraryTagNamesForLimit: (
        tags: Array<{ business_type?: string; name?: string; review_status?: number }>,
        recommended: Array<{ name?: string }> = [],
    ) => {
        const libraryNames = new Set(recommended.map((item) => String(item.name ?? "").trim().toLowerCase()).filter(Boolean));
        const names = new Set<string>();
        for (const tag of tags) {
            const isLibrary = tag.business_type === "tag_library" || libraryNames.has(String(tag.name ?? "").trim().toLowerCase());
            if (!isLibrary) continue;
            if (tag.review_status === 0 || tag.review_status === 2) continue;
            const name = String(tag.name ?? "").trim().toLowerCase();
            if (name) names.add(name);
        }
        return names.size;
    },
    isBoundLibraryTagForLimit: (
        tag: { business_type?: string; name?: string },
        recommended: Array<{ name?: string }> = [],
    ) => {
        if (tag.business_type === "tag_library") return true;
        const normalized = String(tag.name ?? "").trim().toLowerCase();
        return recommended.some((item) => item.name?.trim().toLowerCase() === normalized);
    },
    isBoundLibraryTagName: (tagName: string, recommended: Array<{ name?: string }> = []) => {
        const normalized = tagName.trim().toLowerCase();
        return recommended.some((item) => item.name?.trim().toLowerCase() === normalized);
    },
}));

describe("EditTagsModal recommended tags", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        jest.mocked(useToastContext).mockReturnValue({ showToast: mockShowToast });
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: true });
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            { id: 1, name: "已有标签", business_type: "tag_library", resource_type: "manual_tag" },
            { id: 10, name: "系统A", business_type: "tag_library", resource_type: "system_tag" },
            { id: 11, name: "AI-B", business_type: "tag_library", resource_type: "ai_auto_tag" },
            { id: 12, name: "人工C", business_type: "tag_library", resource_type: "manual_tag" },
        ]);
    });

    it("shows recommended tags grouped by type from bound tag libraries", async () => {
        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("com_knowledge.tag_type_system")).toBeInTheDocument();
            expect(screen.getByText("系统A")).toBeInTheDocument();
            expect(screen.getByText("com_knowledge.tag_type_ai")).toBeInTheDocument();
            expect(screen.getByText("AI-B")).toBeInTheDocument();
            expect(screen.getByText("com_knowledge.tag_type_manual")).toBeInTheDocument();
            expect(screen.getByText("人工C")).toBeInTheDocument();
        });

        expect(getSpaceTagsApi).toHaveBeenCalledWith("100");
    });

    it("dedupes duplicate tag names across system and manual recommended tags", async () => {
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            { id: 10, name: "安全生产", business_type: "tag_library", resource_type: "system_tag" },
            { id: 11, name: "安全生产", business_type: "tag_library", resource_type: "manual_tag" },
        ]);

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("安全生产")).toBeInTheDocument();
            expect(screen.getByText("com_knowledge.tag_type_system")).toBeInTheDocument();
        });

        expect(screen.getAllByText("安全生产")).toHaveLength(1);
        expect(screen.queryByText("com_knowledge.tag_type_manual")).not.toBeInTheDocument();
    });

    it("selects an existing space tag when clicking a recommended tag", async () => {
        const user = userEvent.setup();
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            { id: 2, name: "人工C", business_type: "tag_library", resource_type: "manual_tag" },
        ]);
        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => expect(screen.getByText("人工C")).toBeInTheDocument());

        await user.click(screen.getByText("人工C"));

        await waitFor(() => {
            expect(addSpaceTagApi).not.toHaveBeenCalled();
        });
    });

    it("selects a library tag without creating a new tag when it already exists in space tags", async () => {
        const user = userEvent.setup();

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => expect(screen.getByText("人工C")).toBeInTheDocument());

        await user.click(screen.getByText("人工C"));

        await waitFor(() => {
            expect(addSpaceTagApi).not.toHaveBeenCalled();
        });
    });

    it("saves manually created tags into review_tag_ids", async () => {
        const user = userEvent.setup();
        jest.mocked(getSpaceTagsApi).mockResolvedValue([]);
        jest.mocked(addSpaceTagApi).mockResolvedValue({ id: 99, name: "新手动" });

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => expect(screen.getByRole("textbox")).not.toBeDisabled());

        const input = screen.getByRole("textbox");
        await user.type(input, "新手动");
        await user.keyboard("{Enter}");
        await user.click(screen.getByText("com_knowledge.confirm"));

        await waitFor(() => {
            expect(updateFileTagsApi).toHaveBeenCalledWith("100", "1", [], [99]);
        });
    });

    it("saves selected tags for a single file", async () => {
        const user = userEvent.setup();
        const onClose = jest.fn();
        render(
            <EditTagsModal
                isOpen
                onClose={onClose}
                spaceId="100"
                fileId="1"
                initialTagIds={[1]}
            />,
        );

        await waitFor(() => expect(screen.getByText("系统A")).toBeInTheDocument());
        await user.click(screen.getByText("com_knowledge.confirm"));

        await waitFor(() => {
            expect(updateFileTagsApi).toHaveBeenCalledWith("100", "1", [1], []);
            expect(onClose).toHaveBeenCalledWith(true);
        });
    });

    it("selects a library tag from spaceTags without creating a new tag", async () => {
        const user = userEvent.setup();
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            { id: 200, name: "人工C", business_type: "tag_library", resource_type: "system_tag" },
        ]);

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => expect(screen.getByText("人工C")).toBeInTheDocument());
        await user.click(screen.getByText("人工C"));

        await waitFor(() => {
            expect(addSpaceTagApi).not.toHaveBeenCalled();
        });
    });

    it("hides unapproved recommended tags when review feature is disabled", async () => {
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: false });
        jest.mocked(getSpaceTagsApi).mockResolvedValue([]);

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("com_knowledge.no_tags")).toBeInTheDocument();
        });

        expect(screen.queryByText("AI-B")).not.toBeInTheDocument();
        expect(screen.queryByText("系统A")).not.toBeInTheDocument();
        expect(screen.queryByText("人工C")).not.toBeInTheDocument();
        expect(screen.queryByText("com_knowledge.tag_type_ai")).not.toBeInTheDocument();
    });

    it("shows only approved recommended tags when review feature is disabled", async () => {
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: false });
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            { id: 42, name: "AI-B", resource_type: "ai_auto_tag", business_type: "tag_library" },
            { id: 2, name: "人工C", business_type: "tag_library", resource_type: "manual_tag" },
            { id: 99, name: "系统A", review_status: 0, business_type: "tag_library", resource_type: "system_tag" },
        ]);

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("AI-B")).toBeInTheDocument();
            expect(screen.getByText("人工C")).toBeInTheDocument();
        });

        expect(screen.queryByText("系统A")).not.toBeInTheDocument();
    });

    it("removes pending tags from selection when review feature is disabled", async () => {
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: false });
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            { id: 1, name: "已生效", resource_type: "manual_tag" },
            { id: 2, name: "待审核", review_status: 0, resource_type: "manual_tag" },
        ]);

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[1, 2]}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("已生效")).toBeInTheDocument();
        });

        expect(screen.queryByText("待审核")).not.toBeInTheDocument();
    });

    it("allows selecting approved AI tags when review feature is disabled", async () => {
        const user = userEvent.setup();
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: false });
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            { id: 42, name: "AI-B", resource_type: "ai_auto_tag", business_type: "tag_library" },
        ]);

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => expect(screen.getByText("AI-B")).toBeInTheDocument());
        await user.click(screen.getByText("AI-B"));

        await waitFor(() => {
            expect(addSpaceTagApi).not.toHaveBeenCalled();
            expect(mockShowToast).not.toHaveBeenCalledWith(
                expect.objectContaining({ message: "com_knowledge.review_tag_feature_disabled" }),
            );
        });
    });

    it("does not show unapproved recommended tags when review feature is disabled", async () => {
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: false });
        jest.mocked(getSpaceTagsApi).mockResolvedValue([{ id: 1, name: "已有标签" }]);

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => {
            expect(screen.queryByText("人工C")).not.toBeInTheDocument();
        });

        expect(addSpaceTagApi).not.toHaveBeenCalled();
    });

    it("disables tag input and shows hint when review feature is disabled", async () => {
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: false });

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("com_knowledge.review_tag_input_disabled_placeholder")).toBeInTheDocument();
        });

        const input = screen.getByRole("textbox");
        expect(input).toHaveAttribute("readonly");
        expect(input).not.toBeDisabled();
    });

    it("shows disabled toast when pressing Enter with review feature off", async () => {
        const user = userEvent.setup();
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: false });

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => expect(screen.getByRole("textbox")).toHaveAttribute("readonly"));

        const input = screen.getByRole("textbox");
        await user.click(input);
        await user.keyboard("{Enter}");

        await waitFor(() => {
            expect(mockShowToast).toHaveBeenCalledWith({
                message: "com_knowledge.review_tag_feature_disabled",
                status: "error",
            });
        });
    });

    it("allows selecting recommended library tags even when native tag pool is full", async () => {
        const user = userEvent.setup();
        jest.mocked(getKnowledgeSpaceReviewTagVisibilityApi).mockResolvedValue({ enabled: true });
        const nativeTags = Array.from({ length: 50 }, (_, index) => ({
            id: index + 1,
            name: `native-${index + 1}`,
        }));
        jest.mocked(getSpaceTagsApi).mockResolvedValue([
            ...nativeTags,
            { id: 901, name: "系统A", business_type: "tag_library", resource_type: "system_tag" },
        ]);

        render(
            <EditTagsModal
                isOpen
                onClose={jest.fn()}
                spaceId="100"
                fileId="1"
                initialTagIds={[]}
            />,
        );

        await waitFor(() => expect(screen.getByText("系统A")).toBeInTheDocument());
        await user.click(screen.getByText("系统A"));

        await waitFor(() => {
            expect(addSpaceTagApi).not.toHaveBeenCalled();
        });
    });
});
