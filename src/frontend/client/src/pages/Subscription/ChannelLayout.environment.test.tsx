import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ArticleSearchResultItem } from "~/api/channels";
import { ChannelLayout } from "./ChannelLayout";

const mockNavigate = jest.fn();
let mockChannel = "desktop";
let mockNarrow = false;
let mockHostHeader = false;
let mockWidth = 1200;
let mockResize = () => {};
let mockUnactivate: () => void;
const mockGetDetail = jest.fn<Promise<Partial<ArticleSearchResultItem>>, [string, string]>();
const mockArticle = {
  id: "article",
  channelId: "channel",
  title: "Selected article",
};
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }));
jest.mock("react-activation", () => ({
  useUnactivate: (callback: () => void) => { mockUnactivate = callback; },
}));
jest.mock("recoil", () => ({ useSetRecoilState: () => jest.fn() }));
jest.mock("~/store/subscriptionLayout", () => ({
  subscriptionDetailPaneWidthState: {},
}));
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({
    channel: mockChannel,
    layout: { isNarrowViewport: mockNarrow },
    capabilities: { hasHostChatHeader: mockHostHeader },
  }),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/api/channels", () => ({
  getArticleDetailApi: (articleId: string, channelId: string) => mockGetDetail(articleId, channelId),
}));
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
    onFullScreen,
    embeddedFullscreen,
    onExitEmbeddedFullscreen,
    fullscreenDisabled,
  }: {
    compactMode: boolean;
    onBack?: () => void;
    onFullScreen?: () => void;
    embeddedFullscreen?: boolean;
    onExitEmbeddedFullscreen?: () => void;
    fullscreenDisabled?: boolean;
  }) => (
    <div>
      <output>{compactMode ? "single" : "split"}</output>
      <input aria-label="Article AI draft" />
      <button onClick={onBack}>Back</button>
      {embeddedFullscreen ? (
        <button onClick={onExitEmbeddedFullscreen}>Exit fullscreen</button>
      ) : (
        <button onClick={onFullScreen} disabled={fullscreenDisabled}>Fullscreen</button>
      )}
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
  mockHostHeader = false;
  mockWidth = 1200;
  mockGetDetail.mockResolvedValue({});
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

it.each([false, true])("keeps the current reader and list mounted in fullscreen (mobile app = %s)", async (mobileApp) => {
  mockChannel = mobileApp ? "web" : "desktop";
  mockHostHeader = mobileApp;
  const openFullscreen = jest.fn();
  render(<ChannelLayout channel={{ id: "channel" } as never} onFullScreen={openFullscreen} />);
  const listEntry = screen.getByRole("button", { name: "Read article" });
  await act(async () => fireEvent.click(listEntry));
  const input = screen.getByRole("textbox", { name: "Article AI draft" });
  fireEvent.change(input, { target: { value: "Keep this question" } });
  fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));
  expect(screen.getByRole("button", { name: "Exit fullscreen" })).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toBe(input);
  expect(input).toHaveValue("Keep this question");
  expect(listEntry.parentElement).toHaveClass("invisible");
  expect(openFullscreen).not.toHaveBeenCalled();
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(mockGetDetail).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole("button", { name: "Exit fullscreen" }));
  expect(screen.getByRole("button", { name: "Read article" })).toBe(listEntry);
  expect(listEntry.parentElement).not.toHaveClass("invisible");

  fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));
  act(() => mockUnactivate());
  expect(screen.queryByRole("button", { name: "Exit fullscreen" })).not.toBeInTheDocument();
});

it("waits for detail permission before offering embedded fullscreen", async () => {
  let respond: (data: Partial<ArticleSearchResultItem>) => void = () => {};
  mockGetDetail.mockReturnValueOnce(new Promise(resolve => { respond = resolve; }));
  render(<ChannelLayout channel={{ id: "channel" } as never} />);
  fireEvent.click(screen.getByRole("button", { name: "Read article" }));
  const fullscreen = screen.getByRole("button", { name: "Fullscreen" });
  expect(fullscreen).toBeDisabled();
  await act(async () => respond({
    sensitive_review: { enabled: true, can_view: false, violated: true, hits: [] },
  }));
  expect(fullscreen).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Exit fullscreen" })).not.toBeInTheDocument();
});

it("keeps the existing external fullscreen action in a wide browser", async () => {
  mockChannel = "web";
  const openFullscreen = jest.fn();
  render(<ChannelLayout channel={{ id: "channel" } as never} onFullScreen={openFullscreen} />);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Read article" })));
  fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));
  expect(openFullscreen).toHaveBeenCalledWith(expect.objectContaining({ id: "article" }), false);
});

it("keeps article clicks in the current mobile app WebView on narrow screens", () => {
  mockChannel = "web";
  mockHostHeader = true;
  mockNarrow = true;
  mockWidth = 390;
  render(<ChannelLayout channel={{ id: "channel" } as never} />);
  fireEvent.click(screen.getByRole("button", { name: "Read article" }));
  expect(mockNavigate).toHaveBeenCalledWith("/channel/channel/article/article");
  expect(mockGetDetail).not.toHaveBeenCalled();
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

it.each([
  ["desktop", "488px"],
  ["web", "648px"],
])("keeps %s browse-card width when opening the reading pane", async (channel, expectedWidth) => {
  mockChannel = channel;
  mockWidth = 1280;
  const previousViewportWidth = window.innerWidth;
  window.innerWidth = 1280;
  try {
    const view = render(<ChannelLayout channel={{ id: "channel" } as never} />);
    await act(async () => fireEvent.click(screen.getByText("Read article")));
    expect(screen.getByText("Read article").parentElement).toHaveStyle({ width: expectedWidth });
    expect(screen.getByText("split")).toBeInTheDocument();
    view.unmount();
  } finally {
    window.innerWidth = previousViewportWidth;
  }
});
