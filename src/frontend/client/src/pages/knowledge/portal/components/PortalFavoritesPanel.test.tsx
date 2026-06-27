import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import PortalFavoritesPanel from "./PortalFavoritesPanel";

const mockListFavorites = jest.fn();
const mockRemoveFavorite = jest.fn();
const mockShowToast = jest.fn();

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/api/knowledge", () => ({
    listPortalFavoritesApi: (...args: any[]) => mockListFavorites(...args),
    removePortalFavoriteApi: (...args: any[]) => mockRemoveFavorite(...args),
}));

const space = { id: "fav", name: "我的收藏", isFavorite: true } as any;

function favorite(overrides: Record<string, unknown> = {}) {
    return {
        favoriteFileId: "k1",
        sourceSpaceId: "10",
        sourceFileId: "100",
        title: "有效文件",
        fileName: "valid.pdf",
        status: "valid",
        updatedAt: "2026-01-01",
        ...overrides,
    };
}

beforeEach(() => {
    mockListFavorites.mockReset();
    mockRemoveFavorite.mockReset();
    mockShowToast.mockReset();
});

it("renders an empty placeholder when there are no favorites", async () => {
    mockListFavorites.mockResolvedValue({ data: [], total: 0 });
    render(<PortalFavoritesPanel space={space} onOpenSource={jest.fn()} />);
    expect(await screen.findByTestId("favorites-empty")).toBeInTheDocument();
});

it("marks invalid rows with a tag and disables opening", async () => {
    const onOpenSource = jest.fn();
    mockListFavorites.mockResolvedValue({
        data: [favorite({ favoriteFileId: "bad", status: "invalid", title: "失效文件" })],
        total: 1,
    });
    render(<PortalFavoritesPanel space={space} onOpenSource={onOpenSource} />);

    const tag = await screen.findByTestId("favorite-invalid-tag");
    expect(tag).toHaveTextContent("已失效");

    const row = screen.getByTestId("favorite-row");
    expect(row).toHaveAttribute("data-invalid", "true");

    // The open button (title) is disabled for invalid rows.
    const openButton = screen.getByTitle("源文件已失效，无法打开");
    expect(openButton).toBeDisabled();
    fireEvent.click(openButton);
    expect(onOpenSource).not.toHaveBeenCalled();
});

it("calls onOpenSource when a valid row is clicked", async () => {
    const onOpenSource = jest.fn();
    mockListFavorites.mockResolvedValue({ data: [favorite()], total: 1 });
    render(<PortalFavoritesPanel space={space} onOpenSource={onOpenSource} />);

    const openButton = await screen.findByTitle("有效文件");
    fireEvent.click(openButton);
    expect(onOpenSource).toHaveBeenCalledWith("10", "100", "有效文件");
});

it("removes a favorite and drops it from the list", async () => {
    mockListFavorites.mockResolvedValue({ data: [favorite()], total: 1 });
    mockRemoveFavorite.mockResolvedValue({ removed: true });
    render(<PortalFavoritesPanel space={space} onOpenSource={jest.fn()} />);

    const removeButton = await screen.findByTestId("favorite-remove");
    fireEvent.click(removeButton);

    await waitFor(() => {
        expect(mockRemoveFavorite).toHaveBeenCalledWith({ sourceSpaceId: "10", sourceFileId: "100" });
    });
    await waitFor(() => {
        expect(screen.queryByTestId("favorite-row")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("favorites-empty")).toBeInTheDocument();
});
