import { LoadButton } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio-group";
import { Switch } from "@/components/bs-ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import { toast } from "@/components/bs-ui/toast/use-toast";
import {
  type FileChangePolicyScope,
  getFileChangePolicyApi,
  getFileChangeSettingsApi,
  type KnowledgeSpaceFileChangePolicy,
  type KnowledgeSpaceFileChangeSetting,
  updateFileChangeConfigurationApi,
} from "@/controllers/API/knowledgeSpaceFileChange";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import {
  FormEvent,
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

interface FileChangeApprovalSettingsProps {
  pageSize?: number;
  embedded?: boolean;
}

export interface FileChangeApprovalSettingsHandle {
  save: () => Promise<boolean>;
}

type SettingValues = Record<number, boolean>;

function mergeSettingValues(
  current: SettingValues,
  rows: KnowledgeSpaceFileChangeSetting[],
): SettingValues {
  const next = { ...current };
  rows.forEach((row) => {
    if (next[row.space_id] === undefined) {
      next[row.space_id] = row.approval_required;
    }
  });
  return next;
}

export const FileChangeApprovalSettings = forwardRef<
  FileChangeApprovalSettingsHandle,
  FileChangeApprovalSettingsProps
>(function FileChangeApprovalSettings(
  { pageSize = 20, embedded = false },
  ref,
) {
  const { t } = useTranslation("knowledge");
  const [policyBaseline, setPolicyBaseline] =
    useState<KnowledgeSpaceFileChangePolicy | null>(null);
  const [policyDraft, setPolicyDraft] =
    useState<KnowledgeSpaceFileChangePolicy | null>(null);
  const [rows, setRows] = useState<KnowledgeSpaceFileChangeSetting[]>([]);
  const [settingBaselines, setSettingBaselines] = useState<SettingValues>({});
  const [settingDrafts, setSettingDrafts] = useState<SettingValues>({});
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [policyLoadFailed, setPolicyLoadFailed] = useState(false);
  const [settingsLoadFailed, setSettingsLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const settingsRequestSequence = useRef(0);

  const loadPolicy = useCallback(async () => {
    setPolicyLoading(true);
    setPolicyLoadFailed(false);
    const result = await captureAndAlertRequestErrorHoc(
      getFileChangePolicyApi(),
    );
    if (result && typeof result === "object") {
      const loaded = result as KnowledgeSpaceFileChangePolicy;
      setPolicyBaseline(loaded);
      setPolicyDraft(loaded);
    } else {
      setPolicyLoadFailed(true);
    }
    setPolicyLoading(false);
  }, []);

  const loadSettings = useCallback(async () => {
    const requestSequence = ++settingsRequestSequence.current;
    setSettingsLoading(true);
    setSettingsLoadFailed(false);
    const result = await captureAndAlertRequestErrorHoc(
      getFileChangeSettingsApi({
        keyword: keyword || undefined,
        page,
        page_size: pageSize,
      }),
    );
    if (requestSequence !== settingsRequestSequence.current) return;
    if (result && typeof result === "object") {
      const loaded = result as {
        data: KnowledgeSpaceFileChangeSetting[];
        total: number;
      };
      setRows(loaded.data);
      setTotal(loaded.total);
      setSettingBaselines((current) =>
        mergeSettingValues(current, loaded.data),
      );
      setSettingDrafts((current) => mergeSettingValues(current, loaded.data));
    } else {
      setSettingsLoadFailed(true);
    }
    setSettingsLoading(false);
  }, [keyword, page, pageSize]);

  useEffect(() => {
    void loadPolicy();
  }, [loadPolicy]);

  useEffect(() => {
    void loadSettings();
    return () => {
      settingsRequestSequence.current += 1;
    };
  }, [loadSettings]);

  const changedSpaceIds = useMemo(
    () =>
      Object.keys(settingDrafts)
        .map(Number)
        .filter(
          (spaceId) => settingDrafts[spaceId] !== settingBaselines[spaceId],
        ),
    [settingBaselines, settingDrafts],
  );

  const policyChanged = Boolean(
    policyBaseline &&
    policyDraft &&
    (policyBaseline.enabled !== policyDraft.enabled ||
      policyBaseline.scope !== policyDraft.scope),
  );
  // The per-space list is only shown under the per_space scope. Under all_spaces
  // it is hidden — but any per-space opt-out the user configured earlier stays
  // stored on the backend (we never push per-space changes while the list is
  // hidden), so switching back to per_space restores them.
  const settingsVisible =
    policyDraft?.enabled === true && policyDraft?.scope === "per_space";
  const settingsToSave = settingsVisible ? changedSpaceIds : [];
  const hasChanges = policyChanged || settingsToSave.length > 0;

  const handleScopeChange = (scope: string) => {
    setPolicyDraft((current) =>
      current ? { ...current, scope: scope as FileChangePolicyScope } : current,
    );
  };

  const handleSearch = (event?: FormEvent) => {
    event?.preventDefault();
    setPage(1);
    setKeyword(keywordInput.trim());
  };

  const handleSave = useCallback(async (): Promise<boolean> => {
    if (!policyDraft || saving) return false;
    if (!hasChanges) return true;
    setSaving(true);

    const result = await captureAndAlertRequestErrorHoc(
      updateFileChangeConfigurationApi({
        policy: policyChanged ? policyDraft : undefined,
        settings: settingsToSave.map((spaceId) => ({
          space_id: spaceId,
          approval_required: settingDrafts[spaceId],
        })),
      }),
    );
    const succeeded = result && result !== "canceled";
    if (succeeded) {
      setPolicyBaseline(policyDraft);
      setSettingBaselines((current) => {
        const next = { ...current };
        settingsToSave.forEach((spaceId) => {
          next[spaceId] = settingDrafts[spaceId];
        });
        return next;
      });
      toast({
        title: t("fileChangeApproval.saveSuccess"),
        description: t("fileChangeApproval.saveSuccessHint"),
        variant: "success",
      });
    }
    setSaving(false);
    return Boolean(succeeded);
  }, [
    settingsToSave,
    hasChanges,
    policyChanged,
    policyDraft,
    saving,
    settingDrafts,
    t,
  ]);

  useImperativeHandle(ref, () => ({ save: handleSave }), [handleSave]);

  if (policyLoading) {
    return (
      <div className="flex min-h-48 items-center justify-center text-sm text-muted-foreground">
        {t("fileChangeApproval.loading")}
      </div>
    );
  }

  if (policyLoadFailed || !policyDraft) {
    return (
      <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
        <p role="alert">{t("fileChangeApproval.loadFailed")}</p>
        <LoadButton variant="outline" onClick={() => void loadPolicy()}>
          {t("fileChangeApproval.retry")}
        </LoadButton>
      </div>
    );
  }

  return (
    <section
      className={
        embedded ? "w-full" : "mx-auto w-full max-w-6xl px-2 pb-10"
      }
      aria-labelledby="file-change-approval-title"
    >
      <div
        className={
          embedded
            ? "flex flex-col gap-4 border-t border-[#ECECEC] pt-6 sm:flex-row sm:items-start sm:justify-between"
            : "flex flex-col gap-4 rounded-lg border bg-background p-5 shadow-sm sm:flex-row sm:items-start sm:justify-between"
        }
      >
        <div className="max-w-3xl">
          <h2
            id="file-change-approval-title"
            className="text-lg font-semibold text-foreground"
          >
            {t("fileChangeApproval.title")}
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">
            {t("fileChangeApproval.description")}
          </p>
        </div>
        {!embedded && (
          <LoadButton
            className="min-h-11 min-w-24 self-start"
            loading={saving}
            disabled={!hasChanges}
            onClick={() => void handleSave()}
          >
            {t("fileChangeApproval.save")}
          </LoadButton>
        )}
      </div>

      <div className="mt-4 rounded-lg border bg-background p-5">
        <div className="flex min-h-11 items-center justify-between gap-4">
          <div>
            <label
              htmlFor="file-change-approval-enabled"
              className="font-medium text-foreground"
            >
              {t("fileChangeApproval.enabled")}
            </label>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("fileChangeApproval.enabledHint")}
            </p>
          </div>
          <Switch
            id="file-change-approval-enabled"
            aria-label={t("fileChangeApproval.enabled")}
            checked={policyDraft.enabled}
            onCheckedChange={(enabled) =>
              setPolicyDraft((current) =>
                current ? { ...current, enabled } : current,
              )
            }
          />
        </div>

        <fieldset
          className="mt-5 border-t pt-5"
          disabled={!policyDraft.enabled}
        >
          <legend className="font-medium text-foreground">
            {t("fileChangeApproval.scope.title")}
          </legend>
          <RadioGroup
            className="mt-3 grid gap-3 md:grid-cols-2"
            value={policyDraft.scope}
            onValueChange={handleScopeChange}
            aria-label={t("fileChangeApproval.scope.title")}
          >
            <label
              htmlFor="file-change-scope-all"
              className="flex min-h-14 cursor-pointer items-start gap-3 rounded-md border p-4 transition-colors hover:bg-muted/50 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50"
            >
              <RadioGroupItem
                id="file-change-scope-all"
                value="all_spaces"
                aria-label={t("fileChangeApproval.scope.allSpaces")}
              />
              <span>
                <span className="block text-sm font-medium">
                  {t("fileChangeApproval.scope.allSpaces")}
                </span>
                <span className="mt-1 block text-sm text-muted-foreground">
                  {t("fileChangeApproval.scope.allSpacesHint")}
                </span>
              </span>
            </label>
            <label
              htmlFor="file-change-scope-per-space"
              className="flex min-h-14 cursor-pointer items-start gap-3 rounded-md border p-4 transition-colors hover:bg-muted/50 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50"
            >
              <RadioGroupItem
                id="file-change-scope-per-space"
                value="per_space"
                aria-label={t("fileChangeApproval.scope.perSpace")}
              />
              <span>
                <span className="block text-sm font-medium">
                  {t("fileChangeApproval.scope.perSpace")}
                </span>
                <span className="mt-1 block text-sm text-muted-foreground">
                  {t("fileChangeApproval.scope.perSpaceHint")}
                </span>
              </span>
            </label>
          </RadioGroup>
        </fieldset>
      </div>

      {settingsVisible && (
        <div className="mt-4 rounded-lg border bg-background p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h3 className="font-medium text-foreground">
                {t("fileChangeApproval.spaces.title")}
              </h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("fileChangeApproval.spaces.description")}
              </p>
            </div>
            <form
              className="w-full sm:w-72"
              role="search"
              onSubmit={handleSearch}
            >
              <Input
                type="search"
                value={keywordInput}
                aria-label={t("fileChangeApproval.searchLabel")}
                placeholder={t("fileChangeApproval.searchPlaceholder")}
                onChange={(event) => setKeywordInput(event.target.value)}
              />
            </form>
          </div>

          {settingsLoading ? (
            <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
              {t("fileChangeApproval.loading")}
            </div>
          ) : settingsLoadFailed ? (
            <div className="flex min-h-40 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
              <p role="alert">{t("fileChangeApproval.settingsLoadFailed")}</p>
              <LoadButton variant="outline" onClick={() => void loadSettings()}>
                {t("fileChangeApproval.retry")}
              </LoadButton>
            </div>
          ) : rows.length === 0 ? (
            <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
              {t("fileChangeApproval.empty")}
            </div>
          ) : (
            <>
              <Table className="mt-4 min-w-[680px]" noScroll>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("fileChangeApproval.table.space")}</TableHead>
                    <TableHead>{t("fileChangeApproval.table.kind")}</TableHead>
                    <TableHead>
                      {t("fileChangeApproval.table.visibility")}
                    </TableHead>
                    <TableHead className="text-right">
                      {t("fileChangeApproval.table.required")}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => {
                    const isPrivate = row.auth_type === "private";
                    return (
                      <TableRow key={row.space_id}>
                        <TableCell className="font-medium">
                          {row.name}
                        </TableCell>
                        <TableCell>
                          {row.space_kind === "department" ? (
                            <span className="inline-flex rounded-full border px-2 py-1 text-xs text-muted-foreground">
                              {t("fileChangeApproval.departmentHint")}
                            </span>
                          ) : (
                            t("fileChangeApproval.normalSpace")
                          )}
                        </TableCell>
                        <TableCell>
                          {isPrivate
                            ? t("fileChangeApproval.privateBypass")
                            : t("fileChangeApproval.nonPrivate")}
                        </TableCell>
                        <TableCell className="text-right">
                          <Switch
                            aria-label={`${t("fileChangeApproval.spaceToggleLabel")} ${row.name}`}
                            checked={
                              isPrivate
                                ? false
                                : Boolean(settingDrafts[row.space_id])
                            }
                            disabled={isPrivate}
                            onCheckedChange={(approvalRequired) =>
                              setSettingDrafts((current) => ({
                                ...current,
                                [row.space_id]: approvalRequired,
                              }))
                            }
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {total > pageSize && (
                <AutoPagination
                  className="mt-5"
                  page={page}
                  pageSize={pageSize}
                  total={total}
                  onChange={setPage}
                />
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
});
