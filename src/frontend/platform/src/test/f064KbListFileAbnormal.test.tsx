import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { userContext } from "@/contexts/userContext";
import KnowledgeFile from "@/pages/KnowledgePage/KnowledgeFile";

const testState = vi.hoisted(() => ({ hasAbnormal: true }));
const visibleQuery = vi.hoisted(() => vi.fn());
const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { loadNamespaces: vi.fn() } }) }));
vi.mock("react-router-dom", async () => ({ ...(await vi.importActual<typeof import("react-router-dom")>("react-router-dom")), useNavigate: () => navigate }));
vi.mock("@/controllers/API/permission", () => ({ getMyResourcePermissionsApi: vi.fn() }));
vi.mock("@/controllers/API/knowledgeSpace", async importOriginal => {
  const actual = await importOriginal<typeof import("@/controllers/API/knowledgeSpace")>();
  return { ...actual, knowledgeSpaceApi: { ...actual.knowledgeSpaceApi, listVisibleSpaces: visibleQuery } };
});
vi.mock("@/pages/ModelPage/manage/tabs/WorkbenchModel", () => ({ ModelSelect: () => null }));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({ default: () => null }));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({ KnowledgeHint: () => null, KnowledgeTooltip: ({ children }: { children: ReactNode }) => children }));
const scope = { identityKey: "user:841", tenantId: 60, managementTenantId: 60, view: "ordinary" as const };
const clients: QueryClient[] = [];
function renderPage(page: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client);
  return render(<QueryClientProvider client={client}><MemoryRouter><userContext.Provider value={{ user: { user_id: 841, role: "", web_menu: [] } } as never}>{page}</userContext.Provider></MemoryRouter></QueryClientProvider>);
}

describe("F064 document KB list file abnormal status", () => {
  beforeEach(() => {
    testState.hasAbnormal = true; visibleQuery.mockReset(); navigate.mockReset();
    visibleQuery.mockImplementation(async () => ({ data: [{ id: 41, name: "Policy KB", description: "Description", state: 1, actions: ["visible"], update_time: "2026-09-10T10:00:00", user_name: "Owner", has_abnormal_files: testState.hasAbnormal }], page_size: 20, has_more: false, next_cursor: null }));
  });
  afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });

  it("shows the abnormal tag when the library has failed files", async () => {
    renderPage(<KnowledgeFile scope={scope} />); await screen.findByText("Policy KB");
    expect(screen.getByText("fileStatusAbnormal")).not.toBeNull();
    expect(screen.getByText("fileStatus")).not.toBeNull();
  });
  it("keeps the file status cell empty when no file is abnormal", async () => {
    testState.hasAbnormal = false;
    renderPage(<KnowledgeFile scope={scope} />); await screen.findByText("Policy KB");
    expect(screen.queryByText("fileStatusAbnormal")).toBeNull();
    expect(screen.getByText("fileStatus")).not.toBeNull();
  });
  it("filters the list to abnormal libraries from the column header", async () => {
    renderPage(<KnowledgeFile scope={scope} />); await screen.findByText("Policy KB");
    fireEvent.click(screen.getByRole("combobox", { name: "fileStatusFilterLabel" }));
    fireEvent.click(screen.getByRole("option", { name: "fileStatusAbnormal" }));
    await waitFor(() => expect(visibleQuery).toHaveBeenCalledWith({ page_size: 20, has_abnormal: true }));
  });
  it("opens an abnormal library without prefiltering the file list", async () => {
    renderPage(<KnowledgeFile scope={scope} />);
    fireEvent.click(await screen.findByText("Policy KB"));
    expect(navigate).toHaveBeenCalledWith("/filelib/41");
  });
  it("opens a healthy library without the prefilter", async () => {
    testState.hasAbnormal = false;
    renderPage(<KnowledgeFile scope={scope} />);
    fireEvent.click(await screen.findByText("Policy KB"));
    expect(navigate).toHaveBeenCalledWith("/filelib/41");
  });
});
