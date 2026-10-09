import { fireEvent, render, screen } from "@testing-library/react";

import { ConfirmProvider } from "~/Providers/ConfirmContext";
import { AddSourceDropdown } from "./AddSourceDropdown";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  usePrefersMobileLayout: () => false,
}));

jest.mock("~/components/ui", () => ({
  ...jest.requireActual("~/components/ui/AlertDialog"),
}));

// Source fetching and quota calculations are unrelated to the two visible
// layers; keep the real dropdown and confirmation components in this test.
jest.mock("../hooks/useSourceManager", () => ({
  useSourceManager: () => ({
    activeTab: "official_account",
    filteredSources: [],
    handleCancel: jest.fn(),
    handleClearSearch: jest.fn(),
    handleConfirm: jest.fn(),
    isSearchMode: false,
    isSourceQuotaBlocked: () => false,
    loadMoreSources: jest.fn(),
    pendingSources: [],
    searchKeyword: "",
    selectedIds: new Set(),
    setActiveTab: jest.fn(),
    sourceQuotaLimit: 200,
    sourceQuotaUsed: 0,
    submitSearch: jest.fn(),
    toggleSource: jest.fn(),
    viewMode: "list",
    wechatLinkFailed: false,
  }),
}));

function zIndexOf(element: HTMLElement): number {
  const match = element.className.match(/(?:^|\s)z-\[(\d+)\](?:\s|$)/);
  if (!match) throw new Error("Expected an explicit z-index class");
  return Number(match[1]);
}

it("shows the close confirmation above the expanded source picker", async () => {
  render(
    <ConfirmProvider>
      <AddSourceDropdown
        sources={[]}
        onSourcesChange={jest.fn()}
        expanded
        onExpandChange={jest.fn()}
        onEnqueueCrawl={jest.fn()}
        queueInProgressCount={0}
      />
    </ConfirmProvider>,
  );

  const cancelButton = screen.getByRole("button", { name: "cancel" });
  const sourcePanel = cancelButton.closest(".absolute");
  expect(sourcePanel).not.toBeNull();

  fireEvent.click(cancelButton);

  const confirmation = await screen.findByRole("alertdialog");
  expect(zIndexOf(confirmation)).toBeGreaterThan(zIndexOf(sourcePanel as HTMLElement));
});
