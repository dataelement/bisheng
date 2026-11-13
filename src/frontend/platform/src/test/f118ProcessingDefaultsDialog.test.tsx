import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import {
  knowledgeSpaceApi,
  type ProcessingSettingsRead,
  type ProcessingSettingsWrite,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  useKnowledgeProcessingSettings,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { ProcessingDefaultsDialog, ProcessingDefaultsPanel } from "@/pages/KnowledgePage/components/ProcessingDefaultsDialog";

vi.mock("@/controllers/API", () => ({ getKnowledgeDetailApi: vi.fn() }));
vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "en" },
  }),
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({
  default: () => null,
  ruleI18nMap: {},
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeHint: () => null,
  KnowledgeTooltip: ({ children }: { children: React.ReactNode }) => children,
}));
const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const settings: ProcessingSettingsRead = {
  space_id: 7,
  config_version: 4,
  saved_defaults: null,
  effective_defaults: {
    schema_version: 1,
    document: {
      split_mode: "custom",
      separator: ["\\n", ""],
      separator_rule: ["after", "after"],
      chunk_size: 300,
      chunk_overlap: 20,
      hierarchy_level: 3,
      append_title: false,
      max_chunk_size: 600,
      retain_images: 1,
      force_ocr: 1,
      enable_formula: 0,
      filter_page_header_footer: 1,
    },
    table: {
      slice_length: 10,
      header_start_row: 1,
      header_end_row: 2,
      append_header: 0,
    },
  },
};
const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.clearAllMocks();
});
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const api = {
    ...knowledgeSpaceApi,
    getProcessingSettings: vi.fn().mockResolvedValue(settings),
    updateProcessingSettings: vi.fn(
      async (
        _: number,
        body: ProcessingSettingsWrite,
      ): Promise<ProcessingSettingsRead> => ({
        ...settings,
        config_version: 5,
        saved_defaults: body.defaults,
        effective_defaults: body.defaults,
      }),
    ),
    createProcessingJob: vi.fn(),
  };
  const changed = vi.fn(),
    saved = vi.fn();
  const draw = (value = scope, open = true, spaceId = 7) => (
    <QueryClientProvider client={client}>
      <ProcessingDefaultsDialog
        scope={value}
        spaceId={spaceId}
        open={open}
        onOpenChange={changed}
        onSaved={saved}
        api={api}
      />
    </QueryClientProvider>
  );
  return { client, api, changed, saved, draw };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
const ready = () => screen.findByRole("spinbutton", { name: "splitLength" });

it("echoes effective defaults inline and uses the saved revision on the next save", async () => {
  const f = setup();
  render(<QueryClientProvider client={f.client}><ProcessingDefaultsPanel scope={scope} spaceId={7} api={f.api} /></QueryClientProvider>);
  expect(await ready()).toHaveValue("300");
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.change(await ready(), { target: { value: "450" } });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(f.api.updateProcessingSettings).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByRole("button", { name: "save" })).not.toBeDisabled());
  expect(await ready()).toHaveValue("450");
  fireEvent.change(await ready(), { target: { value: "500" } });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(f.api.updateProcessingSettings).toHaveBeenCalledTimes(2));
  expect(f.api.updateProcessingSettings.mock.calls[1][1]).toEqual(expect.objectContaining({ expected_config_version: 5 }));
});

it("retires an unfinished opening read before reopening with a new settings version", async () => {
  const f = setup(),
    old = deferred<ProcessingSettingsRead>();
  f.api.getProcessingSettings
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce({
      ...settings,
      config_version: 9,
      effective_defaults: {
        ...settings.effective_defaults,
        document: { ...settings.effective_defaults.document, chunk_size: 700 },
      },
    });
  const view = render(f.draw());
  await waitFor(() =>
    expect(f.api.getProcessingSettings).toHaveBeenCalledTimes(1),
  );
  view.rerender(f.draw(scope, false));
  view.rerender(f.draw());
  await act(async () => old.resolve(settings));
  await ready();
  expect(screen.getByRole("spinbutton", { name: "splitLength" })).toHaveValue(
    "700",
  );
  expect(f.api.getProcessingSettings).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() =>
    expect(f.api.updateProcessingSettings).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ expected_config_version: 9 }),
    ),
  );
});

it("does not let an unmounted opening read populate an otherwise unobserved cache", async () => {
  const f = setup(),
    old = deferred<ProcessingSettingsRead>();
  f.api.getProcessingSettings.mockReturnValueOnce(old.promise);
  const view = render(f.draw());
  await waitFor(() =>
    expect(f.api.getProcessingSettings).toHaveBeenCalledTimes(1),
  );
  view.unmount();
  await act(async () => old.resolve(settings));
  expect(
    f.client.getQueryData(knowledgeQueryKeys.settings(scope, 7)),
  ).toBeUndefined();
});

it("keeps another active settings reader's shared request alive when the dialog closes", async () => {
  const f = setup(),
    response = deferred<ProcessingSettingsRead>();
  f.api.getProcessingSettings.mockReturnValueOnce(response.promise);
  function OtherReader() {
    const query = useKnowledgeProcessingSettings(scope, 7, f.api);
    return (
      <output data-testid="other-reader">{query.data?.config_version}</output>
    );
  }
  const draw = (open: boolean) => (
    <QueryClientProvider client={f.client}>
      <OtherReader />
      <ProcessingDefaultsDialog
        scope={scope}
        spaceId={7}
        open={open}
        onOpenChange={f.changed}
        api={f.api}
      />
    </QueryClientProvider>
  );
  const view = render(draw(true));
  await waitFor(() =>
    expect(f.api.getProcessingSettings).toHaveBeenCalledTimes(1),
  );
  view.rerender(draw(false));
  await act(async () => response.resolve(settings));
  await waitFor(() =>
    expect(screen.getByTestId("other-reader")).toHaveTextContent("4"),
  );
  expect(f.client.getQueryData(knowledgeQueryKeys.settings(scope, 7))).toEqual(
    settings,
  );
  expect(f.api.getProcessingSettings).toHaveBeenCalledTimes(1);
});

it.each([
  { value: { ...scope, identityKey: "" }, spaceId: 7 },
  { value: { ...scope, tenantId: 0 }, spaceId: 7 },
  { value: { ...scope, tenantId: 1.5 }, spaceId: 7 },
  { value: scope, spaceId: 0 },
  { value: scope, spaceId: Number.NaN },
])(
  "keeps the settings hook disabled for an incomplete query scope %#",
  async ({ value, spaceId }) => {
    const f = setup();
    render(f.draw(value, true, spaceId));
    await act(async () => {
      await Promise.resolve();
    });
    expect(f.api.getProcessingSettings).not.toHaveBeenCalled();
    expect(f.api.updateProcessingSettings).not.toHaveBeenCalled();
    expect(screen.queryByRole("spinbutton")).toBeNull();
  },
);

it("reads only when open, then saves both actual types with the issuing version and no job", async () => {
  const f = setup(),
    view = render(f.draw(scope, false));
  expect(f.api.getProcessingSettings).not.toHaveBeenCalled();
  view.rerender(f.draw());
  const length = await ready();
  fireEvent.change(length, { target: { value: "501" } });
  const newer = { ...settings, config_version: 99 };
  act(() =>
    f.client.setQueryData(knowledgeQueryKeys.settings(scope, 7), newer),
  );
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(f.changed).toHaveBeenCalledWith(false));
  expect(f.api.updateProcessingSettings).toHaveBeenCalledWith(7, {
    expected_config_version: 4,
    defaults: {
      ...settings.effective_defaults,
      document: { ...settings.effective_defaults.document, chunk_size: 501 },
    },
  });
  expect(f.saved.mock.lastCall?.[0].config_version).toBe(5);
  expect(f.api.createProcessingJob).not.toHaveBeenCalled();
  expect(settings.effective_defaults.document.chunk_size).toBe(300);
});

it("cancel and invalid hidden table rules never issue a write", async () => {
  const f = setup();
  render(f.draw());
  await ready();
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.tables" }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "f118.header_start" }),
    { target: { value: "9" } },
  );
  fireEvent.mouseDown(screen.getByRole("tab", { name: "f118.documents" }), {
    button: 0,
    ctrlKey: false,
  });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  expect(f.api.updateProcessingSettings).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(f.changed).toHaveBeenCalledWith(false);
  expect(f.saved).not.toHaveBeenCalled();
});

it.each([10998, 19000])(
  "retains the draft and original saved value after server/CAS failure %s",
  async (code) => {
    const f = setup(),
      error = { status_code: code, data: { reason: "original" } };
    f.api.updateProcessingSettings.mockRejectedValueOnce(error);
    render(f.draw());
    fireEvent.change(await ready(), { target: { value: "501" } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(error));
    expect(screen.getByRole("spinbutton", { name: "splitLength" })).toHaveValue(
      "501",
    );
    expect(f.changed).not.toHaveBeenCalled();
    expect(f.saved).not.toHaveBeenCalled();
    expect(settings.config_version).toBe(4);
  },
);

it("does not substitute defaults on read failure and supports an explicit retry", async () => {
  const f = setup();
  f.api.getProcessingSettings.mockRejectedValueOnce(new Error("load failed"));
  render(f.draw());
  await screen.findByText("f118.load_failed");
  expect(screen.queryByRole("spinbutton")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await ready();
  expect(f.api.getProcessingSettings).toHaveBeenCalledTimes(2);
});

it("discards an old scope's late query instead of seeding the next draft", async () => {
  const f = setup(),
    first = deferred<ProcessingSettingsRead>();
  f.api.getProcessingSettings
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce({
      ...settings,
      config_version: 9,
      effective_defaults: {
        ...settings.effective_defaults,
        document: { ...settings.effective_defaults.document, chunk_size: 700 },
      },
    });
  const view = render(f.draw());
  await waitFor(() =>
    expect(f.api.getProcessingSettings).toHaveBeenCalledTimes(1),
  );
  view.rerender(f.draw({ ...scope, managementTenantId: 202 }));
  await waitFor(() =>
    expect(screen.getByRole("spinbutton", { name: "splitLength" })).toHaveValue(
      "700",
    ),
  );
  await act(async () => first.resolve(settings));
  expect(screen.getByRole("spinbutton", { name: "splitLength" })).toHaveValue(
    "700",
  );
});

it("reloads actual settings after reopening instead of reviving the cancelled draft or stale cache", async () => {
  const f = setup(),
    view = render(f.draw());
  fireEvent.change(await ready(), { target: { value: "501" } });
  view.rerender(f.draw(scope, false));
  f.api.getProcessingSettings.mockResolvedValueOnce({
    ...settings,
    config_version: 9,
    effective_defaults: {
      ...settings.effective_defaults,
      document: { ...settings.effective_defaults.document, chunk_size: 700 },
    },
  });
  view.rerender(f.draw());
  await waitFor(() =>
    expect(screen.getByRole("spinbutton", { name: "splitLength" })).toHaveValue(
      "700",
    ),
  );
  expect(f.api.getProcessingSettings).toHaveBeenCalledTimes(2);
});

it("rechecks the issuing epoch after awaiting cache invalidation before publishing save success", async () => {
  const f = setup(),
    invalidation = deferred<void>(),
    view = render(f.draw());
  const invalidate = vi
    .spyOn(f.client, "invalidateQueries")
    .mockReturnValueOnce(invalidation.promise);
  await ready();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(1));
  expect(invalidate).toHaveBeenCalledWith({
    queryKey: knowledgeQueryKeys.settings(scope, 7),
  });
  view.rerender(f.draw({ ...scope, managementTenantId: 202 }));
  await ready();
  await act(async () => invalidation.resolve());
  expect(f.saved).not.toHaveBeenCalled();
  expect(f.changed).not.toHaveBeenCalled();
});

it.each(["scope", "close", "unmount"])(
  "rejects a late save after %s without closing or invalidating a new dialog",
  async (operation) => {
    const f = setup(),
      response = deferred<ProcessingSettingsRead>();
    f.api.updateProcessingSettings.mockReturnValueOnce(response.promise);
    const invalidate = vi.spyOn(f.client, "invalidateQueries"),
      view = render(f.draw());
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() =>
      expect(f.api.updateProcessingSettings).toHaveBeenCalledTimes(1),
    );
    if (operation === "unmount") view.unmount();
    else if (operation === "close") view.rerender(f.draw(scope, false));
    else {
      view.rerender(f.draw({ ...scope, managementTenantId: 202 }));
      await ready();
      view.rerender(f.draw());
      await ready();
    }
    await act(async () => response.resolve({ ...settings, config_version: 5 }));
    expect(f.changed).not.toHaveBeenCalled();
    expect(f.saved).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
  },
);


it("keeps automatic settings unchanged when the legacy UI hides custom parameters", async () => {
  const f = setup();
  const automatic = { ...settings, effective_defaults: { ...settings.effective_defaults, document: { ...settings.effective_defaults.document, split_mode: "auto" as const, chunk_overlap: 0 } } };
  f.api.getProcessingSettings.mockResolvedValue(automatic);
  render(f.draw());
  expect(await screen.findByRole("radio", { name: /autoSplit/ })).toHaveAttribute("aria-checked", "true");
  expect(screen.queryByRole("spinbutton", { name: "splitLength" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(f.api.updateProcessingSettings).toHaveBeenCalledWith(7, { expected_config_version: 4, defaults: automatic.effective_defaults }));
});
