import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import type { Article } from "~/api/channels";
import { ArticleDetail } from "./ArticleDetail";

const article: Article = {
  id: "article",
  channelId: "channel",
  title: "Article title",
  url: "https://example.com/article",
  content: "Article summary",
  content_html: "<p>Article body</p>",
  sourceName: "Source name",
  sourceId: "source",
  isRead: true,
  publishedAt: "2026-10-16T00:00:00Z",
  createdAt: "2026-10-16T00:00:00Z",
};
const mockShare = jest.fn();

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  usePrefersMobileLayout: () => false,
}));
jest.mock("~/hooks/AuthContext", () => ({ useAuthContext: () => ({ user: null }) }));
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("~/utils", () => ({ formatTime: () => "2026-10-16" }));
jest.mock("~/components/icons", () => ({ AiChatIcon: () => null }));
jest.mock("bisheng-icons", () => ({ Outlined: new Proxy({}, { get: () => () => <svg /> }) }));
jest.mock("@bisheng/ui", () => {
  const React = jest.requireActual<typeof import("react")>("react");
  return {
    Button: React.forwardRef<HTMLButtonElement, ComponentPropsWithoutRef<"button">>(
      ({ children, onClick, "aria-label": label }, ref) => (
        <button ref={ref} onClick={onClick} aria-label={label}>{children}</button>
      ),
    ),
    Tooltip: ({ children }: { children: ReactNode }) => children,
  };
});
jest.mock("../hooks/useArticleShare", () => ({ useArticleShare: () => ({ handleShare: mockShare }) }));
jest.mock("../AiChat/ArticleAiDock", () => ({ ArticleAiDock: () => <input aria-label="Ask about article" /> }));
jest.mock("./AddToKnowledgeModal", () => ({
  AddToKnowledgeModal: ({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) => open ? (
    <div role="dialog">
      <button onClick={() => onOpenChange(false)}>Close knowledge picker</button>
    </div>
  ) : null,
}));

function Reader() {
  const [fullscreen, setFullscreen] = useState(false);
  return <ArticleDetail
    article={article}
    embeddedFullscreen={fullscreen}
    onFullScreen={() => setFullscreen(true)}
    onExitEmbeddedFullscreen={() => setFullscreen(false)}
  />;
}

it("keeps the same iframe document and Ask input while expanding and closing from the frame", () => {
  const { container } = render(<Reader />);
  const iframe = container.querySelector("iframe");
  const frameDocument = iframe?.contentDocument;
  if (!iframe || !frameDocument) throw new Error("Expected an article iframe");
  const srcDoc = iframe.srcdoc;
  const input = screen.getByRole("textbox", { name: "Ask about article" });
  fireEvent.change(input, { target: { value: "My question" } });

  fireEvent.click(screen.getByRole("button", { name: "com_subscription.fullscreen" }));
  expect(screen.getByRole("button", { name: "com_ui_go_back" })).toHaveFocus();
  expect(container.querySelector("iframe")).toBe(iframe);
  expect(iframe.srcdoc).toBe(srcDoc);
  expect(iframe.contentDocument).toBe(frameDocument);
  expect(frameDocument.documentElement).toHaveAttribute("data-embedded-fullscreen");
  expect(screen.getByRole("textbox", { name: "Ask about article" })).toBe(input);
  expect(input).toHaveValue("My question");

  fireEvent.keyDown(frameDocument, { key: "Escape" });
  expect(screen.getByRole("button", { name: "com_subscription.fullscreen" })).toHaveFocus();
  expect(frameDocument.documentElement).not.toHaveAttribute("data-embedded-fullscreen");
});

it("preserves reader actions and lets the nested knowledge picker own Escape", () => {
  const open = jest.spyOn(window, "open").mockImplementation(() => null);
  render(<Reader />);
  fireEvent.click(screen.getByRole("button", { name: "com_subscription.fullscreen" }));
  fireEvent.click(screen.getByRole("button", { name: "com_subscription.original_webpage" }));
  fireEvent.click(screen.getByRole("button", { name: "com_subscription.share" }));
  expect(open).toHaveBeenCalledWith(article.url);
  expect(mockShare).toHaveBeenCalledWith(article);

  fireEvent.click(screen.getByRole("button", { name: "com_subscription.add_to_knowledge_space" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.getByRole("button", { name: "com_ui_go_back" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Close knowledge picker" }));
  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("button", { name: "com_ui_go_back" })).not.toBeInTheDocument();
});
