import { fireEvent, render, screen } from "@testing-library/react";
import { getSquareSpacesApi } from "~/api/knowledge";
import request from "~/api/request";
import KnowledgeSquareCard from "./KnowledgeSquareCard";

jest.mock("~/api/request", () => ({
    __esModule: true,
    default: { get: jest.fn() },
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));

async function loadSpace(avatar: string | null) {
    jest.mocked(request.get).mockResolvedValueOnce({
        data: {
            total: 1,
            data: [{
                space: { id: 1, name: "Example space", icon: "/assets/space.svg" },
                user_name: "Alice",
                avatar,
            }],
        },
    });
    const { data: [space] } = await getSquareSpacesApi();
    return space;
}

it("resolves the creator's signed avatar and swaps it for the initial when the image fails", async () => {
    jest.replaceProperty(__APP_ENV__, "BASE_URL", "/workspace");
    const signedPath = "/object/bisheng/avatar/1/picture.png?signature=a%2Bb";
    const space = await loadSpace(signedPath);
    render(<KnowledgeSquareCard space={space} status="joined" />);

    expect(space.icon).toBe("/assets/space.svg");
    const avatar = screen.getByRole("img", { name: "Alice" });
    expect(avatar).toHaveAttribute("src", `/workspace${signedPath}`);
    expect(screen.queryByText("A")).not.toBeInTheDocument();

    fireEvent.error(avatar);
    expect(screen.queryByRole("img", { name: "Alice" })).not.toBeInTheDocument();
    expect(screen.getByText("A")).toHaveClass("bg-fill-4", "text-white");
});

it("uses the initial when only the space icon is set", async () => {
    const space = await loadSpace(null);
    render(<KnowledgeSquareCard space={space} status="joined" />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("A")).toBeVisible();
});
