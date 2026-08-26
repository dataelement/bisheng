import { fireEvent, render, screen } from "@testing-library/react";

import en from "~/locales/en/translation.json";
import { WechatLinkHint } from "./WechatLinkHint";

// `mock*` prefix: jest hoists the factory above the imports and only lets it
// reach out-of-scope bindings named this way.
const mockBundle = en as unknown as Record<string, Record<string, string>>;

// The real useLocalize reads a Recoil atom (frozen: no `recoil` imports allowed
// in new code), so stand in for it with the shipped English bundle plus the same
// `{{...}}` interpolation — the sentence and its `{{link}}` placeholder stay real.
jest.mock("~/hooks/useLocalize", () => ({
  __esModule: true,
  default:
    () =>
    (key: string, options?: Record<string, string>) => {
      const [namespace, name] = key.split(".");
      const raw = mockBundle[namespace]?.[name] ?? key;
      return raw.replace(/\{\{(\w+)\}\}/g, (_, token) => options?.[token] ?? "");
    },
}));

const FINE_POINTER_QUERY = "(hover: hover) and (pointer: fine)";
// Read the copy back from the locale file so a wording change moves the test
// with it — the assertions are about structure, not about these sentences.
const LINK_LABEL = en.com_subscription.wechat_article_link_label;
const COPY_TIP = en.com_subscription.wechat_link_copy_tip;

beforeAll(() => {
  // Radix measures the popover arrow with a ResizeObserver, which jsdom lacks.
  if (!window.ResizeObserver) {
    Object.defineProperty(window, "ResizeObserver", {
      writable: true,
      configurable: true,
      value: jest.fn().mockImplementation(() => ({
        observe: jest.fn(),
        unobserve: jest.fn(),
        disconnect: jest.fn(),
      })),
    });
  }
});

function mockPointer({ fine }: { fine: boolean }) {
  // Assignment, not defineProperty: the shared matchMedia mock installs a
  // non-configurable (but writable) property, so redefining it throws.
  window.matchMedia = jest.fn().mockImplementation((query: string) => ({
    matches: query === FINE_POINTER_QUERY ? fine : false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })) as unknown as typeof window.matchMedia;
}

function renderHint() {
  return render(
    <WechatLinkHint
      sentenceKey="com_subscription.no_source_collected"
      labelKey="com_subscription.wechat_article_link_label"
    />,
  );
}

describe("WechatLinkHint copy-link guide", () => {
  it("splits the sentence on the localized phrase so a trigger always exists", () => {
    mockPointer({ fine: true });
    renderHint();

    // Guards the `{{link}}` contract: a translation that dropped the
    // placeholder falls back to plain text with nothing to open the guide.
    expect(screen.getByText(LINK_LABEL)).toBeInTheDocument();
  });

  it("stays a hover-only tooltip where a fine pointer exists", () => {
    mockPointer({ fine: true });
    renderHint();

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("becomes a tappable popover when the pointer is coarse", () => {
    mockPointer({ fine: false });
    renderHint();

    const trigger = screen.getByRole("button", { name: LINK_LABEL });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(trigger);

    // A Radix Tooltip is unreachable by touch, so the guide screenshot plus its
    // caption have to come from a popover — otherwise touch users lose it.
    const guide = screen.getByRole("dialog");
    expect(guide).toContainElement(screen.getByRole("img"));
    expect(guide).toHaveTextContent(COPY_TIP);
  });
});
