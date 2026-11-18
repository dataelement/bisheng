import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { notification } from "@bisheng/ui";
import { SpaceFileUploadPanel } from "@/pages/KnowledgePage/components/SpaceFileUploadPanel";
import { uploadSettings } from "./uploadWizardFixtures";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), error: vi.fn() }));
vi.mock("@/controllers/request", () => ({ default: mocks, showApiError: mocks.error }));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({ appConfig: { enableEtl4lm: true, enableMediaUpload: true } }),
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({ KnowledgeHint: () => null, KnowledgeTooltip: () => null }));
vi.mock("@/pages/KnowledgePage/components/PreviewParagraph", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({ default: () => null }));
const scope = { identityKey: "user:7", tenantId: 101, managementTenantId: 101, view: "ordinary" as const };
let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  mocks.get.mockImplementation((url: string) => url.endsWith("/upload-settings") ? Promise.resolve(uploadSettings()) : new Promise(() => {}));
  mocks.post.mockImplementation(async (url: string) => {
    if (url.endsWith("/uploads")) return { file_path: "tmp/video.mp4", upload_id: "a".repeat(32), repeat: false };
    if (url.endsWith("/previews")) return { preview_id: "b".repeat(32) };
    if (url.endsWith("/files")) return [{ id: 81, knowledge_id: 7, file_name: "video.mp4", status: 2 }];
    throw new Error(`Unexpected request ${url}`);
  });
});
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("keeps preview navigation actionable and allows direct upload during a pending media preview", async () => {
  vi.stubGlobal("BRAND_CONFIG", { URLLoadingIcon: "/assets/custom-preview-loading.svg" });
  const notice = vi.spyOn(notification, "open");
  render(<MemoryRouter><QueryClientProvider client={client}><SpaceFileUploadPanel scope={scope} spaceId={7} parentId={9} /></QueryClientProvider></MemoryRouter>);
  await act(async () => fireEvent.change(document.querySelector('input[type="file"]')!, { target: { files: [new File(["x"], "video.mp4", { type: "video/mp4" })] } }));
  await waitFor(() => expect(screen.getByRole("button", { name: "nextStep" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  fireEvent.click(await screen.findByRole("button", { name: "previewResults" }));
  const loading = (await screen.findByText("f118.preview_loading")).closest('[role="status"]');
  expect(loading).toHaveAttribute("aria-busy", "true");
  expect(loading?.querySelector("img")).toHaveAttribute("src", "/assets/custom-preview-loading.svg");
  await waitFor(() => expect(mocks.get.mock.calls.some(([url]) => url.includes("/previews/"))).toBe(true));
  expect(screen.getByRole("button", { name: "nextStep" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  expect(notice).toHaveBeenCalledWith(expect.objectContaining({ description: "previewInProgress" }));
  expect(mocks.post.mock.calls.filter(([url]) => url.endsWith("/files"))).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "uploadDirectlyDefaults" }));
  await waitFor(() => expect(mocks.post.mock.calls.some(([url]) => url.endsWith("/files"))).toBe(true));
  const [, body] = mocks.post.mock.calls.find(([url]) => url.endsWith("/files"))!;
  expect(body.upload_context.mode).toBe("direct");
  expect(body.upload_context.items[0].preview_id).toBeUndefined();
});
