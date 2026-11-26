import { refreshClientEnvironment } from "~/utils/clientEnvironment";
import { act, render, screen } from "@testing-library/react";
import i18n from "~/locales/i18n";
import useLocalize from "~/hooks/useLocalize";
import { rememberDesktopLocale } from "~/locales/desktopLocale";
import { useDesktopLocale } from "./useDesktopLocale";
import translationZh from "~/locales/zh-Hans/translation.json";

jest.unmock("react-i18next");
jest.mock("recoil", () => ({ useRecoilValue: () => "en" }));
jest.mock("~/store", () => ({ __esModule: true, default: { lang: {} } }));

function Shell({ children }: { children?: React.ReactNode }) {
  useDesktopLocale();
  return <>{children}</>;
}

function Page() {
  const localize = useLocalize();
  return <div>{localize("com_knowledge.knowledge_space")}</div>;
}

beforeEach(async () => {
  window.history.replaceState({}, "", "/workspace/");
  window.sessionStorage.clear();
  delete window.dshChatPresentation;
  delete document.documentElement.dataset.dshHostLocale;
  refreshClientEnvironment();
  await i18n.changeLanguage("en");
});

afterEach(() => {
  delete window.dshChatPresentation;
});

it("does not persist host language when a Web document enters desktop through SPA navigation", async () => {
  const detector = i18n.services.languageDetector as unknown as {
    options: { caches: string[] };
  };
  detector.options.caches = ["localStorage"];
  localStorage.setItem("i18nextLng", "en");
  const view = render(
    <Shell>
      <Page />
    </Shell>,
  );
  await act(async () => {
    window.dshChatPresentation = { reportLanding: jest.fn() };
    window.history.replaceState({}, "", "/workspace/?embed=dsh&dshLocale=zh");
    refreshClientEnvironment();
  });
  expect(
    await screen.findByText(translationZh.com_knowledge.knowledge_space),
  ).toBeInTheDocument();
  expect(localStorage.getItem("i18nextLng")).toBe("en");
  view.unmount();
});

it("switches existing and newly mounted pages while retaining the saved web preference", async () => {
  const saved = localStorage.getItem("lang");
  window.dshChatPresentation = { reportLanding: jest.fn() };
  window.history.replaceState({}, "", "/workspace/?embed=dsh&dshLocale=zh");
  refreshClientEnvironment();
  const ui = render(
    <Shell>
      <Page />
    </Shell>,
  );
  expect(
    await screen.findByText(translationZh.com_knowledge.knowledge_space),
  ).toBeInTheDocument();
  await act(async () =>
    window.dispatchEvent(
      new CustomEvent("dsh:locale", { detail: { locale: "en" } }),
    ),
  );
  expect(await screen.findByText("Knowledge Space")).toBeInTheDocument();
  await act(async () =>
    window.dispatchEvent(
      new CustomEvent("dsh:locale", { detail: { locale: "zh" } }),
    ),
  );
  ui.rerender(
    <Shell>
      <Page key="another-module" />
    </Shell>,
  );
  expect(
    await screen.findByText(translationZh.com_knowledge.knowledge_space),
  ).toBeInTheDocument();
  expect(localStorage.getItem("lang")).toBe(saved);
  ui.unmount();
  await act(async () =>
    window.dispatchEvent(
      new CustomEvent("dsh:locale", { detail: { locale: "en" } }),
    ),
  );
  expect(i18n.language).toBe("zh-Hans");
});

it("keeps standalone pages on their saved web language even when a host-like event arrives", async () => {
  rememberDesktopLocale("zh");
  render(
    <Shell>
      <Page />
    </Shell>,
  );
  await act(async () =>
    window.dispatchEvent(
      new CustomEvent("dsh:locale", { detail: { locale: "zh" } }),
    ),
  );
  expect(await screen.findByText("Knowledge Space")).toBeInTheDocument();
  expect(i18n.language).toBe("en");
});
