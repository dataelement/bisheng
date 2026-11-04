import { act, fireEvent, render, screen } from "@testing-library/react";
import { ChannelLayout } from "./ChannelLayout";

const mockNavigate = jest.fn();
let mockChannel = "desktop";
let mockNarrow = false;
let mockWidth = 1200;
let mockResize = () => {};
const mockArticle = {
  id: "article",
  channelId: "channel",
  title: "Selected article",
};
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }));
jest.mock("recoil", () => ({ useSetRecoilState: () => jest.fn() }));
jest.mock("~/store/subscriptionLayout", () => ({
  subscriptionDetailPaneWidthState: {},
}));
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({
    channel: mockChannel,
    layout: { isNarrowViewport: mockNarrow },
  }),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/api/channels", () => ({ getArticleDetailApi: async () => ({}) }));
jest.mock("~/components/Nav/NavToggle", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("./ArticleList/ArticleList", () => ({
  ArticleList: ({
    onArticleSelect,
  }: {
    onArticleSelect: (article: unknown) => void;
  }) => (
    <button onClick={() => onArticleSelect(mockArticle)}>Read article</button>
  ),
}));
jest.mock("./Article/ArticleDetail", () => ({
  ArticleDetail: ({
    compactMode,
    onBack,
  }: {
    compactMode: boolean;
    onBack?: () => void;
  }) => (
    <div>
      <output>{compactMode ? "single" : "split"}</output>
      <input aria-label="Article AI draft" />
      <button onClick={onBack}>Back</button>
    </div>
  ),
}));
jest.mock("./AiChat/AiAssistantPanel", () => ({
  AiAssistantPanel: () => null,
}));
jest.mock("~/utils", () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(" "),
}));

beforeEach(() => {
  mockChannel = "desktop";
  mockNarrow = false;
  mockWidth = 1200;
  localStorage.clear();
  global.ResizeObserver = jest
    .fn()
    .mockImplementation((callback: () => void) => {
      mockResize = callback;
      return { observe: jest.fn(), disconnect: jest.fn() };
    });
  jest
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(
      () => ({ width: mockWidth, height: 600, left: 0 }) as DOMRect,
    );
});

it("retains one detail and draft through the actual container capacity boundary", async () => {
  render(<ChannelLayout channel={{ id: "channel" } as never} />);
  await act(async () => fireEvent.click(screen.getByText("Read article")));
  const input = screen.getByRole("textbox", { name: "Article AI draft" });
  fireEvent.change(input, { target: { value: "Keep this question" } });
  for (const width of [961, 960, 820, 600, 390, 0, 1200]) {
    act(() => {
      mockWidth = width;
      mockResize();
    });
    expect(screen.getByRole("textbox")).toBe(input);
    expect(input).toHaveValue("Keep this question");
    expect(
      screen.getByText(width >= 961 ? "split" : "single"),
    ).toBeInTheDocument();
  }
  expect(mockNavigate).not.toHaveBeenCalled();
});
it("preserves Web narrow article route navigation while host narrow content stays in place", async () => {
  mockChannel = "web";
  mockNarrow = true;
  mockWidth = 390;
  render(<ChannelLayout channel={{ id: "channel" } as never} />);
  fireEvent.click(screen.getByText("Read article"));
  expect(mockNavigate).toHaveBeenCalledWith("/channel/channel/article/article");
  expect(screen.queryByRole("textbox")).toBeNull();
});
it("releases drag cursor and selection when capacity is lost", async () => {
  const view = render(<ChannelLayout channel={{ id: "channel" } as never} />);
  await act(async () => fireEvent.click(screen.getByText("Read article")));
  const splitter = view.container.querySelector(".cursor-col-resize");
  expect(splitter).not.toBeNull();
  fireEvent.mouseDown(splitter!);
  expect(document.body.style.cursor).toBe("col-resize");
  act(() => {
    mockWidth = 600;
    mockResize();
  });
  expect(document.body.style.cursor).toBe("");
  expect(document.body.style.userSelect).toBe("");
  view.unmount();
});
