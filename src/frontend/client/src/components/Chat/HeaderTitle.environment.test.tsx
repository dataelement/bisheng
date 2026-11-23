import { render, screen } from "@testing-library/react";
import HeaderTitle from "./HeaderTitle";

let mockChannel = "web";
let mockPathname = "/c/123";
let mockHostChatHeader = false;
let mockNarrowViewport = true;
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({
    channel: mockChannel,
    capabilities: { hasHostChatHeader: mockHostChatHeader },
    layout: { isNarrowViewport: mockNarrowViewport },
  }),
}));
jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  useMediaQuery: () => true,
}));
jest.mock("react-router-dom", () => ({
  useLocation: () => ({ pathname: mockPathname }),
}));
jest.mock("~/utils", () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(" "),
}));
jest.mock("../Share/ShareChat", () => ({
  __esModule: true,
  default: () => <button>Share</button>,
}));

beforeEach(() => {
  mockChannel = "web";
  mockPathname = "/c/123";
  mockHostChatHeader = false;
  mockNarrowViewport = true;
});

it("keeps title/share in narrow desktop chat where the web global top bar is absent", () => {
  mockChannel = "desktop";
  render(<HeaderTitle conversation={{ title: "Current chat" }} />);
  expect(screen.getByText("Current chat")).toBeVisible();
  expect(screen.getByRole("button", { name: "Share" })).toBeVisible();
});
it("lets the visible web or app compact top bar own the title/share", () => {
  mockChannel = "web";
  const view = render(<HeaderTitle conversation={{ title: "Current chat" }} />);
  expect(screen.queryByText("Current chat")).toBeNull();
  mockChannel = "desktop";
  mockPathname = "/app/123/456/5";
  view.rerender(<HeaderTitle conversation={{ title: "Current chat" }} />);
  expect(screen.queryByText("Current chat")).toBeNull();
});

it("does not bring back a fallback title bar when the mobile App rotates into a wide viewport", () => {
  mockNarrowViewport = false;
  const view = render(<HeaderTitle conversation={{ title: "Current chat" }} />);
  expect(screen.getByText("Current chat")).toBeVisible();
  mockHostChatHeader = true;
  view.rerender(<HeaderTitle conversation={{ title: "Current chat" }} />);
  expect(view.container).toBeEmptyDOMElement();
});
