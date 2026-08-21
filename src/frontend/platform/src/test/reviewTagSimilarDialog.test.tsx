import { ApproveReviewTagDialog } from "@/pages/BuildPage/bench/reviewTag/ApproveReviewTagDialog";
import { BatchApproveLibraryPickerDialog } from "@/pages/BuildPage/bench/standalone/tagConsole/TagBatchDialogs";
import { TagReviewDialog } from "@/pages/BuildPage/bench/standalone/tagConsole/TagReviewDialog";
import { render, screen, waitFor, within } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toastMock = vi.fn();
const approveOrRejectReviewTagApi = vi.fn();
const getKnowledgeSpaceTagLibrariesApi = vi.fn();
const getKnowledgeSpaceTagLibrariesByKnowledgeApi = vi.fn();
const getTagConsoleReviewDetailApi = vi.fn();

const similarCheckState = {
    result: null as {
        exact_matches: { name: string; match_kind: string; score?: number | null }[];
        similar_matches: { name: string; match_kind: string; score?: number | null }[];
        similarity_threshold?: number;
    } | null,
    loading: false,
    hasSimilar: false,
};

const similarBatchCheckState = {
    result: null as {
        items: {
            tag_name: string;
            exact_matches: { name: string; match_kind: string; score?: number | null }[];
            similar_matches: { name: string; match_kind: string; score?: number | null }[];
        }[];
        similarity_threshold?: number;
    } | null,
    loading: false,
    hasSimilar: false,
    similarItems: [] as {
        tag_name: string;
        exact_matches: { name: string; match_kind: string; score?: number | null }[];
        similar_matches: { name: string; match_kind: string; score?: number | null }[];
    }[],
};

vi.mock("react-i18next", () => ({
    useTranslation: () => ({
        t: (key: string, fallback?: string | Record<string, unknown>, options?: Record<string, unknown>) => {
            if (typeof fallback === "string") {
                let text = fallback;
                const vars = options ?? (typeof fallback === "object" ? fallback : undefined);
                if (vars) {
                    for (const [name, value] of Object.entries(vars)) {
                        text = text.replace(`{{${name}}}`, String(value));
                    }
                }
                return text;
            }
            const labels: Record<string, string> = {
                cancel: "取消",
                confirm: "确认",
                close: "关闭",
            };
            return labels[key] ?? key;
        },
    }),
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
    useToast: () => ({ toast: toastMock }),
}));

vi.mock("@/controllers/request", () => ({
    captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown> | unknown) => Promise.resolve(promise)),
}));

vi.mock("@/controllers/API/knowledgeSpaceTagLibrary", () => ({
    approveOrRejectReviewTagApi: (...args: unknown[]) => approveOrRejectReviewTagApi(...args),
    getKnowledgeSpaceTagLibrariesApi: (...args: unknown[]) => getKnowledgeSpaceTagLibrariesApi(...args),
    getKnowledgeSpaceTagLibrariesByKnowledgeApi: (...args: unknown[]) => getKnowledgeSpaceTagLibrariesByKnowledgeApi(...args),
    getTagConsoleReviewDetailApi: (...args: unknown[]) => getTagConsoleReviewDetailApi(...args),
}));

vi.mock("@/pages/BuildPage/bench/reviewTag/useReviewTagSimilarCheck", () => ({
    useReviewTagSimilarCheck: () => similarCheckState,
}));

vi.mock("@/pages/BuildPage/bench/reviewTag/useReviewTagSimilarBatchCheck", () => ({
    useReviewTagSimilarBatchCheck: () => similarBatchCheckState,
}));

vi.mock("@/pages/BuildPage/bench/standalone/tagConsole/useApprovableLibraries", () => ({
    useApprovableLibraries: () => ({
        libraries: [{ id: 10, name: "业务标签库", description: "", tag_count: 1, is_builtin: false }],
        loading: false,
    }),
    distinctSourceSpaceIds: () => [100],
}));

vi.mock("@/pages/BuildPage/bench/standalone/tagConsole/SourceFileLinks", () => ({
    SourceFileLinks: () => <span>source-files</span>,
}));

vi.mock("@/pages/BuildPage/bench/standalone/tagConsole/TagSourceIcon", () => ({
    tagSourceLabel: () => "AI标签",
}));

vi.mock("@/components/bs-ui/select", () => ({
    Select: ({
        children,
        value,
        onValueChange,
        disabled,
    }: {
        children: React.ReactNode;
        value?: string;
        onValueChange: (value: string) => void;
        disabled?: boolean;
    }) => (
        <select
            aria-label="library-select"
            value={value || ""}
            disabled={disabled}
            onChange={(event) => onValueChange(event.target.value)}
        >
            <option value="">请选择标签库</option>
            {children}
        </select>
    ),
    SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    SelectItem: ({ children, value }: { children: React.ReactNode; value: string }) => (
        <option value={value}>{children}</option>
    ),
    SelectTrigger: () => null,
    SelectValue: () => null,
}));

vi.mock("@/components/bs-ui/input", async () => {
    const React = await import("react");
    return {
        Textarea: React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>((props, ref) => (
            <textarea ref={ref} {...props} />
        )),
    };
});

const libraries = [{ id: 10, name: "业务标签库", description: "", tag_count: 1, is_builtin: false }];

function resetSimilarState() {
    similarCheckState.result = null;
    similarCheckState.loading = false;
    similarCheckState.hasSimilar = false;
    similarBatchCheckState.result = null;
    similarBatchCheckState.loading = false;
    similarBatchCheckState.hasSimilar = false;
    similarBatchCheckState.similarItems = [];
}

describe("review tag similar dialog interactions", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        resetSimilarState();
        getKnowledgeSpaceTagLibrariesByKnowledgeApi.mockResolvedValue(libraries);
        getKnowledgeSpaceTagLibrariesApi.mockResolvedValue({ data: libraries, total: 1 });
        approveOrRejectReviewTagApi.mockResolvedValue(true);
        getTagConsoleReviewDetailApi.mockResolvedValue({
            name: "机器学习",
            resource_type: "ai_auto_tag",
            submitter_name: "Alice",
            library_name: "默认库",
            source_files: [{ knowledge_id: 100, file_name: "demo.pdf" }],
        });
    });

    it("ApproveReviewTagDialog approves directly when no similar tags are found", async () => {
        const user = userEvent.setup();
        const onApproved = vi.fn();

        render(
            <ApproveReviewTagDialog
                open
                row={{ tag_name: "机器学习", resource_type: "ai_auto_tag" }}
                knowledgeId={100}
                onOpenChange={vi.fn()}
                onApproved={onApproved}
            />,
        );

        await waitFor(() => {
            expect(screen.getByLabelText("library-select")).not.toBeDisabled();
        });

        await user.selectOptions(screen.getByLabelText("library-select"), "10");
        await user.click(screen.getByRole("button", { name: "确认" }));

        await waitFor(() => {
            expect(approveOrRejectReviewTagApi).toHaveBeenCalledWith({
                tag_name: "机器学习",
                status: 1,
                resource_type: "ai_auto_tag",
                tag_library_id: 10,
                knowledge_id: 100,
                ack_similar: false,
            });
        });
        expect(onApproved).toHaveBeenCalled();
        expect(screen.queryByText("确认仍要通过？")).not.toBeInTheDocument();
    });

    it("ApproveReviewTagDialog requires second confirmation when similar tags exist", async () => {
        const user = userEvent.setup();
        similarCheckState.hasSimilar = true;
        similarCheckState.result = {
            exact_matches: [],
            similar_matches: [{ name: "机器学习-模型训练", match_kind: "substring", score: null }],
            similarity_threshold: 0.85,
        };

        render(
            <ApproveReviewTagDialog
                open
                row={{ tag_name: "机器学习", resource_type: "ai_auto_tag" }}
                knowledgeId={100}
                onOpenChange={vi.fn()}
                onApproved={vi.fn()}
            />,
        );

        await waitFor(() => {
            expect(screen.getByLabelText("library-select")).not.toBeDisabled();
        });

        await user.selectOptions(screen.getByLabelText("library-select"), "10");
        expect(screen.getByText("目标库存在相似标签")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "继续审核" })).toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: "继续审核" }));
        expect(screen.getByText("确认仍要通过？")).toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: "仍要通过" }));

        await waitFor(() => {
            expect(approveOrRejectReviewTagApi).toHaveBeenCalledWith({
                tag_name: "机器学习",
                status: 1,
                resource_type: "ai_auto_tag",
                tag_library_id: 10,
                knowledge_id: 100,
                ack_similar: true,
            });
        });
    });

    it("TagReviewDialog forwards ack_similar=false when no similar tags exist", async () => {
        const user = userEvent.setup();
        const onApprove = vi.fn();

        render(
            <TagReviewDialog
                target={{ tag_name: "机器学习", resource_type: "ai_auto_tag" }}
                libraries={libraries}
                saving={false}
                onClose={vi.fn()}
                onApprove={onApprove}
                onReject={vi.fn()}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("机器学习")).toBeInTheDocument();
        });

        await user.selectOptions(screen.getByLabelText("library-select"), "10");
        await user.click(screen.getByRole("button", { name: "同意" }));

        expect(onApprove).toHaveBeenCalledWith(10, false);
    });

    it("TagReviewDialog opens confirm dialog and passes ack_similar=true when similar tags exist", async () => {
        const user = userEvent.setup();
        const onApprove = vi.fn();
        similarCheckState.hasSimilar = true;
        similarCheckState.result = {
            exact_matches: [],
            similar_matches: [{ name: "机器学习-模型训练", match_kind: "substring", score: null }],
            similarity_threshold: 0.85,
        };

        render(
            <TagReviewDialog
                target={{ tag_name: "机器学习", resource_type: "ai_auto_tag" }}
                libraries={libraries}
                saving={false}
                onClose={vi.fn()}
                onApprove={onApprove}
                onReject={vi.fn()}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText("机器学习")).toBeInTheDocument();
        });

        await user.selectOptions(screen.getByLabelText("library-select"), "10");
        await user.click(screen.getByRole("button", { name: "继续审核" }));
        await user.click(screen.getByRole("button", { name: "仍要通过" }));

        expect(onApprove).toHaveBeenCalledWith(10, true);
    });

    it("BatchApproveLibraryPickerDialog confirms batch approve with ack_similar=true", async () => {
        const user = userEvent.setup();
        const onConfirm = vi.fn();
        similarBatchCheckState.hasSimilar = true;
        similarBatchCheckState.similarItems = [
            {
                tag_name: "机器学习",
                exact_matches: [],
                similar_matches: [{ name: "机器学习-模型训练", match_kind: "substring", score: null }],
            },
        ];
        similarBatchCheckState.result = {
            items: similarBatchCheckState.similarItems,
            similarity_threshold: 0.85,
        };

        render(
            <BatchApproveLibraryPickerDialog
                open
                title="批量审核通过"
                tagNames={["机器学习", "深度学习"]}
                libraries={libraries}
                saving={false}
                onOpenChange={vi.fn()}
                onConfirm={onConfirm}
            />,
        );

        await user.selectOptions(screen.getByLabelText("library-select"), "10");
        expect(screen.getByText("1 个标签在目标库中存在相似标签")).toBeInTheDocument();

        await user.click(screen.getByRole("button", { name: "继续审核" }));
        const confirmDialog = screen.getByRole("alertdialog");
        expect(within(confirmDialog).getByText("确认仍要通过？")).toBeInTheDocument();
        expect(within(confirmDialog).getByText("机器学习")).toBeInTheDocument();

        await user.click(within(confirmDialog).getByRole("button", { name: "仍要通过" }));
        expect(onConfirm).toHaveBeenCalledWith(10, true);
    });

    it("BatchApproveLibraryPickerDialog approves directly when no similar tags exist", async () => {
        const user = userEvent.setup();
        const onConfirm = vi.fn();

        render(
            <BatchApproveLibraryPickerDialog
                open
                title="批量审核通过"
                tagNames={["新标签A"]}
                libraries={libraries}
                saving={false}
                onOpenChange={vi.fn()}
                onConfirm={onConfirm}
            />,
        );

        await user.selectOptions(screen.getByLabelText("library-select"), "10");
        await user.click(screen.getByRole("button", { name: "确认" }));

        expect(onConfirm).toHaveBeenCalledWith(10, false);
    });
});
