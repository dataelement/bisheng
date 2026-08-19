import {
  getFileChangePolicyApi,
  getFileChangeSettingsApi,
  updateFileChangeConfigurationApi,
  updateFileChangePolicyApi,
  updateFileChangeSettingApi,
} from "@/controllers/API/knowledgeSpaceFileChange";
import KnowledgePage from "@/pages/KnowledgePage";
import {
  FileChangeApprovalSettings,
  type FileChangeApprovalSettingsHandle,
} from "@/pages/KnowledgePage/FileChangeApprovalSettings";
import { act, fireEvent, render, screen, waitFor, within } from "@/test/test-utils";
import enKnowledge from "../../public/locales/en-US/knowledge.json";
import jaKnowledge from "../../public/locales/ja/knowledge.json";
import zhKnowledge from "../../public/locales/zh-Hans/knowledge.json";
import { createRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const requestMocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
}));
const toastMock = vi.hoisted(() => vi.fn());

vi.mock("@/controllers/request", () => ({
  default: requestMocks,
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) =>
    promise.catch(() => false),
  ),
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: toastMock,
}));

vi.mock("@/components/bs-icons", () => ({
  LoadIcon: () => <span data-testid="loading-icon" />,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@/pages/KnowledgePage/KnowledgeFile", () => ({
  default: () => <div data-testid="knowledge-file" />,
}));

vi.mock("@/pages/KnowledgePage/KnowledgeQa", () => ({
  default: () => <div data-testid="knowledge-qa" />,
}));

const policy = { enabled: true, scope: "per_space" as const };
const settingsPage = {
  data: [
    {
      space_id: 101,
      name: "Public Space",
      auth_type: "public",
      space_kind: "normal" as const,
      approval_required: true,
      effective_required: true,
    },
    {
      space_id: 102,
      name: "Private Space",
      auth_type: "private",
      space_kind: "normal" as const,
      approval_required: true,
      effective_required: false,
    },
    {
      space_id: 103,
      name: "Department Space",
      auth_type: "public",
      space_kind: "department" as const,
      approval_required: false,
      effective_required: false,
    },
  ],
  total: 3,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function scalarPaths(value: unknown, prefix = ""): string[] {
  if (value === null || typeof value !== "object") return [prefix];
  return Object.entries(value).flatMap(([key, child]) =>
    scalarPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

function mockInitialRequests() {
  requestMocks.get.mockImplementation((url: string) => {
    if (url.endsWith("file-change-policy")) return Promise.resolve(policy);
    if (url.endsWith("file-change-settings"))
      return Promise.resolve(settingsPage);
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
  requestMocks.put.mockImplementation((url: string, body: unknown) => {
    if (url.endsWith("file-change-configuration")) {
      const payload = body as {
        policy?: typeof policy;
        settings?: { space_id: number; approval_required: boolean }[];
      };
      return Promise.resolve({
        policy: payload.policy ?? policy,
        settings: (payload.settings ?? []).map((item) => ({
          ...settingsPage.data.find((row) => row.space_id === item.space_id),
          approval_required: item.approval_required,
          effective_required: item.approval_required,
        })),
      });
    }
    if (url.endsWith("file-change-policy")) return Promise.resolve(body);
    const spaceId = Number(url.split("/").at(-1));
    const current = settingsPage.data.find((row) => row.space_id === spaceId);
    return Promise.resolve({ ...current, ...(body as object) });
  });
}

describe("knowledge space file-change approval API client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialRequests();
  });

  it("uses current-tenant endpoints without accepting a tenant id", async () => {
    await getFileChangePolicyApi();
    await updateFileChangePolicyApi({ enabled: false, scope: "all_spaces" });
    await getFileChangeSettingsApi({
      keyword: "space",
      page: 2,
      page_size: 10,
    });
    await updateFileChangeSettingApi(101, { approval_required: false });
    await updateFileChangeConfigurationApi({
      policy: { enabled: true, scope: "per_space" },
      settings: [{ space_id: 101, approval_required: false }],
    });

    expect(requestMocks.get).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge/space/admin/file-change-policy",
    );
    expect(requestMocks.put).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge/space/admin/file-change-policy",
      { enabled: false, scope: "all_spaces" },
    );
    expect(requestMocks.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/knowledge/space/admin/file-change-settings",
      { params: { keyword: "space", page: 2, page_size: 10 } },
    );
    expect(requestMocks.put).toHaveBeenNthCalledWith(
      2,
      "/api/v1/knowledge/space/admin/file-change-settings/101",
      { approval_required: false },
    );
    expect(requestMocks.put).toHaveBeenNthCalledWith(
      3,
      "/api/v1/knowledge/space/admin/file-change-configuration",
      {
        policy: { enabled: true, scope: "per_space" },
        settings: [{ space_id: 101, approval_required: false }],
      },
    );
    expect(JSON.stringify(requestMocks.get.mock.calls)).not.toContain(
      "tenant_id",
    );
    expect(JSON.stringify(requestMocks.put.mock.calls)).not.toContain(
      "tenant_id",
    );
  });
});

describe("FileChangeApprovalSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialRequests();
  });

  it("loads the enabled per-space default without writing anything", async () => {
    render(<FileChangeApprovalSettings />);

    const enabledSwitch = await screen.findByRole("switch", {
      name: "fileChangeApproval.enabled",
    });
    expect(enabledSwitch).toBeChecked();
    expect(
      screen.getByRole("radio", { name: "fileChangeApproval.scope.perSpace" }),
    ).toBeChecked();
    expect(requestMocks.put).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "fileChangeApproval.save" }),
    ).toBeDisabled();
  });

  it("keeps edits local until save and only advances the baseline after success", async () => {
    render(<FileChangeApprovalSettings />);
    const enabledSwitch = await screen.findByRole("switch", {
      name: "fileChangeApproval.enabled",
    });

    fireEvent.click(enabledSwitch);
    expect(requestMocks.put).not.toHaveBeenCalled();

    const saveButton = screen.getByRole("button", {
      name: "fileChangeApproval.save",
    });
    expect(saveButton).toBeEnabled();
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(updateFileChangePolicyApi).toBeDefined();
      expect(requestMocks.put).toHaveBeenCalledWith(
        "/api/v1/knowledge/space/admin/file-change-configuration",
        { policy: { enabled: false, scope: "per_space" }, settings: [] },
      );
      expect(saveButton).toBeDisabled();
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ variant: "success" }),
    );
  });

  it("does not report success or discard the draft when save fails", async () => {
    requestMocks.put.mockRejectedValueOnce(new Error("save failed"));
    render(<FileChangeApprovalSettings />);
    const enabledSwitch = await screen.findByRole("switch", {
      name: "fileChangeApproval.enabled",
    });
    fireEvent.click(enabledSwitch);

    const saveButton = screen.getByRole("button", {
      name: "fileChangeApproval.save",
    });
    fireEvent.click(saveButton);

    await waitFor(() => expect(requestMocks.put).toHaveBeenCalledTimes(1));
    expect(saveButton).toBeEnabled();
    expect(enabledSwitch).not.toBeChecked();
    expect(toastMock).not.toHaveBeenCalledWith(
      expect.objectContaining({ variant: "success" }),
    );
  });

  it("hides the per-space list under all_spaces and preserves stored settings on save", async () => {
    requestMocks.put
      .mockRejectedValueOnce(new Error("configuration save failed"))
      .mockResolvedValueOnce({
        policy: { enabled: true, scope: "all_spaces" },
        settings: [],
      });
    render(<FileChangeApprovalSettings />);

    // The per-space list is visible under the default per_space scope.
    const publicRow = (await screen.findByText("Public Space")).closest(
      "tr",
    ) as HTMLElement;
    // A per-space draft made before switching scope must not be pushed on save.
    fireEvent.click(within(publicRow).getByRole("switch"));

    fireEvent.click(
      screen.getByRole("radio", { name: "fileChangeApproval.scope.allSpaces" }),
    );
    // Switching to all_spaces hides the per-space list entirely.
    expect(screen.queryByText("Public Space")).not.toBeInTheDocument();

    const saveButton = screen.getByRole("button", {
      name: "fileChangeApproval.save",
    });
    fireEvent.click(saveButton);

    await waitFor(() => expect(requestMocks.put).toHaveBeenCalledTimes(1));
    expect(saveButton).toBeEnabled();
    expect(toastMock).not.toHaveBeenCalledWith(
      expect.objectContaining({ variant: "success" }),
    );

    fireEvent.click(saveButton);
    await waitFor(() => expect(requestMocks.put).toHaveBeenCalledTimes(2));
    // Only the policy is saved; no per-space settings are sent, so previously
    // stored per-space opt-outs are preserved on the backend.
    expect(requestMocks.put).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/admin/file-change-configuration",
      {
        policy: { enabled: true, scope: "all_spaces" },
        settings: [],
      },
    );
    await waitFor(() => expect(saveButton).toBeDisabled());
  });

  it("retains per-space drafts when the master switch is closed and reopened", async () => {
    render(<FileChangeApprovalSettings />);
    const publicRow = (await screen.findByText("Public Space")).closest(
      "tr",
    ) as HTMLElement;
    const publicSwitch = within(publicRow).getByRole("switch");
    fireEvent.click(publicSwitch);
    expect(publicSwitch).not.toBeChecked();

    const enabledSwitch = screen.getByRole("switch", {
      name: "fileChangeApproval.enabled",
    });
    fireEvent.click(enabledSwitch);
    expect(screen.queryByText("Public Space")).not.toBeInTheDocument();
    fireEvent.click(enabledSwitch);

    const reopenedRow = (await screen.findByText("Public Space")).closest(
      "tr",
    ) as HTMLElement;
    expect(within(reopenedRow).getByRole("switch")).not.toBeChecked();
  });

  it("disables private spaces and identifies department spaces", async () => {
    render(<FileChangeApprovalSettings />);
    const privateRow = (await screen.findByText("Private Space")).closest(
      "tr",
    ) as HTMLElement;
    const departmentRow = screen
      .getByText("Department Space")
      .closest("tr") as HTMLElement;

    expect(within(privateRow).getByRole("switch")).toBeDisabled();
    expect(
      within(privateRow).getByText("fileChangeApproval.privateBypass"),
    ).toBeInTheDocument();
    expect(
      within(departmentRow).getByText("fileChangeApproval.departmentHint"),
    ).toBeInTheDocument();
  });

  it("queries by keyword and changes pages", async () => {
    const manySettings = { ...settingsPage, total: 21 };
    requestMocks.get.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("file-change-policy") ? policy : manySettings,
      ),
    );
    render(<FileChangeApprovalSettings pageSize={20} />);
    await screen.findByText("Public Space");

    fireEvent.change(
      screen.getByRole("searchbox", { name: "fileChangeApproval.searchLabel" }),
      { target: { value: "Public" } },
    );
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() => {
      expect(requestMocks.get).toHaveBeenCalledWith(
        "/api/v1/knowledge/space/admin/file-change-settings",
        { params: { keyword: "Public", page: 1, page_size: 20 } },
      );
    });

    fireEvent.click(screen.getByLabelText("Go to next page"));
    await waitFor(() => {
      expect(requestMocks.get).toHaveBeenCalledWith(
        "/api/v1/knowledge/space/admin/file-change-settings",
        { params: { keyword: "Public", page: 2, page_size: 20 } },
      );
    });
  });

  it("keeps only the latest settings response when searches finish out of order", async () => {
    const oldSearch = deferred<typeof settingsPage>();
    const latestSearch = deferred<typeof settingsPage>();
    let settingsCalls = 0;
    requestMocks.get.mockImplementation((url: string) => {
      if (url.endsWith("file-change-policy")) return Promise.resolve(policy);
      settingsCalls += 1;
      if (settingsCalls === 1) return Promise.resolve(settingsPage);
      if (settingsCalls === 2) return oldSearch.promise;
      if (settingsCalls === 3) return latestSearch.promise;
      return Promise.reject(new Error(`Unexpected settings request ${settingsCalls}`));
    });
    render(<FileChangeApprovalSettings />);
    await screen.findByText("Public Space");

    const search = screen.getByRole("searchbox", {
      name: "fileChangeApproval.searchLabel",
    });
    fireEvent.change(search, { target: { value: "Public" } });
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() => expect(settingsCalls).toBe(2));

    fireEvent.change(search, { target: { value: "Department" } });
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() => expect(settingsCalls).toBe(3));

    await act(async () => {
      latestSearch.resolve({
        data: [settingsPage.data[2]],
        total: 1,
      });
    });
    expect(await screen.findByText("Department Space")).toBeInTheDocument();

    await act(async () => {
      oldSearch.resolve({
        data: [settingsPage.data[0]],
        total: 1,
      });
    });
    expect(screen.getByText("Department Space")).toBeInTheDocument();
    expect(screen.queryByText("Public Space")).not.toBeInTheDocument();
  });

  it("uses the parent save action when embedded in workbench settings", async () => {
    const ref = createRef<FileChangeApprovalSettingsHandle>();
    render(<FileChangeApprovalSettings ref={ref} embedded />);

    const enabledSwitch = await screen.findByRole("switch", {
      name: "fileChangeApproval.enabled",
    });
    expect(
      screen.queryByRole("button", { name: "fileChangeApproval.save" }),
    ).not.toBeInTheDocument();

    fireEvent.click(enabledSwitch);
    await act(async () => {
      expect(await ref.current?.save()).toBe(true);
    });
    expect(requestMocks.put).toHaveBeenCalledWith(
      "/api/v1/knowledge/space/admin/file-change-configuration",
      { policy: { enabled: false, scope: "per_space" }, settings: [] },
    );
  });
});

describe("knowledge file-change approval locales", () => {
  it("keeps every scalar key path aligned across the three real locale files", () => {
    const sections = [
      zhKnowledge.fileChangeApproval,
      enKnowledge.fileChangeApproval,
      jaKnowledge.fileChangeApproval,
    ];
    const expectedPaths = scalarPaths(sections[0]).sort();

    sections.forEach((section) => {
      expect(scalarPaths(section).sort()).toEqual(expectedPaths);
      expect(section.tab).toBeTruthy();
    });
  });
});

describe("KnowledgePage file-change approval entry", () => {
  it("removes the legacy approval settings tab from the knowledge library", () => {
    render(<KnowledgePage />);
    expect(
      screen.queryByRole("tab", { name: "fileChangeApproval.tab" }),
    ).not.toBeInTheDocument();
  });
});
