import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";

import {
    FileType,
    SpaceRole,
    VisibilityType,
    getDepartmentSpacesApi,
    getJoinedSpacesApi,
    getMineSpacesApi,
    getSpaceChildrenApi,
    type KnowledgeSpace,
} from "~/api/knowledge";
import { listUploadableSpacesApi } from "~/api/messageExport";
import { MoveToDialog } from "./MoveToDialog";

jest.mock("bisheng-icons", () => ({
    Outlined: {
        City: (props: any) => <span data-testid="city-icon" {...props} />,
        Down: (props: any) => <span data-testid="down-icon" {...props} />,
        File: (props: any) => <span data-testid="file-icon" {...props} />,
        FileImage: (props: any) => <span data-testid="file-image-icon" {...props} />,
        FolderClose: (props: any) => <span data-testid="folder-icon" {...props} />,
        Notebook: (props: any) => <span data-testid="notebook-icon" {...props} />,
        Right: (props: any) => <span data-testid="right-icon" {...props} />,
    },
}));

jest.mock("lucide-react", () => ({
    Loader2: (props: any) => <span data-testid="loader" {...props} />,
}));

jest.mock("~/components/ui/Button", () => ({
    Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
}));

jest.mock("~/components/ui/Dialog", () => ({
    Dialog: ({ open, children }: any) => (open ? <div>{children}</div> : null),
    DialogContent: ({ children }: any) => <div>{children}</div>,
    DialogFooter: ({ children }: any) => <div>{children}</div>,
    DialogHeader: ({ children }: any) => <div>{children}</div>,
    DialogTitle: ({ children }: any) => <h2>{children}</h2>,
}));

jest.mock("~/components/ui/ExpandableSearchField", () => ({
    ExpandableSearchField: ({ value, onChange, placeholder }: any) => (
        <input aria-label={placeholder} value={value} onChange={(event) => onChange(event.target.value)} />
    ),
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock("../hooks/useDynamicEllipsis", () => ({
    useDynamicEllipsis: jest.fn(),
}));

jest.mock("../sidebar/DynamicEllipsisName", () => ({
    DynamicEllipsisName: ({ name, trailing }: any) => (
        <span>
            {name}
            {trailing}
        </span>
    ),
}));

jest.mock("./MoveToFolderTree", () => ({
    MoveToFolderTree: () => <div data-testid="folder-tree" />,
}));

jest.mock("~/api/messageExport", () => ({
    listUploadableSpacesApi: jest.fn(),
}));

jest.mock("~/api/knowledge", () => ({
    FileType: {
        FOLDER: "folder",
        PDF: "pdf",
    },
    SpaceRole: {
        CREATOR: "creator",
        ADMIN: "admin",
        MEMBER: "member",
    },
    VisibilityType: {
        PUBLIC: "public",
        PRIVATE: "private",
        APPROVAL: "approval",
    },
    SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED: [2],
    getDepartmentSpacesApi: jest.fn(),
    getJoinedSpacesApi: jest.fn(),
    getMineSpacesApi: jest.fn(),
    getSpaceChildrenApi: jest.fn(),
}));

function makeSpace(id: string, name: string): KnowledgeSpace {
    return {
        id,
        name,
        description: "",
        icon: "",
        visibility: VisibilityType.PRIVATE,
        creator: "tester",
        creatorId: "user-1",
        memberCount: 1,
        fileCount: 0,
        totalFileCount: 0,
        role: SpaceRole.MEMBER,
        isPinned: false,
        createdAt: "",
        updatedAt: "",
        tags: [],
        isReleased: true,
    };
}

function renderDialog() {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    return render(
        <QueryClientProvider client={queryClient}>
            <MoveToDialog
                open
                onOpenChange={() => undefined}
                currentSpaceId="current-space"
                currentSpaceName="Current Space"
                onConfirm={() => undefined}
            />
        </QueryClientProvider>,
    );
}

describe("MoveToDialog", () => {
    test("shows children for the first visible uploadable space when current space is not uploadable", async () => {
        const targetSpace = makeSpace("target-space", "Target Space");
        jest.mocked(listUploadableSpacesApi).mockResolvedValue([
            { id: targetSpace.id, name: targetSpace.name },
        ]);
        jest.mocked(getDepartmentSpacesApi).mockResolvedValue([]);
        jest.mocked(getMineSpacesApi).mockResolvedValue([makeSpace("current-space", "Current Space")]);
        jest.mocked(getJoinedSpacesApi).mockResolvedValue([targetSpace]);
        jest.mocked(getSpaceChildrenApi).mockResolvedValue({
            data: [
                {
                    id: "folder-1",
                    name: "Target Folder",
                    type: FileType.FOLDER,
                    tags: [],
                    path: "Target Folder",
                    spaceId: targetSpace.id,
                    createdAt: "",
                    updatedAt: "",
                },
            ],
            page_size: 200,
            has_more: false,
            next_cursor: null,
        } as any);

        renderDialog();

        expect(screen.getByText("com_knowledge.move_empty_folder")).toBeInTheDocument();

        await waitFor(() => {
            expect(getSpaceChildrenApi).toHaveBeenCalledWith(
                expect.objectContaining({
                    space_id: targetSpace.id,
                    file_status: [2],
                }),
            );
        });

        expect(getSpaceChildrenApi).not.toHaveBeenCalledWith(
            expect.objectContaining({ space_id: "current-space" }),
        );
        expect(await screen.findByText("Target Folder")).toBeInTheDocument();
    });
});
