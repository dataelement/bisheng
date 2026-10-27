import { Button, SearchInput } from '@bisheng/ui';
import { Tooltip as SharedTooltip, Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";



import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { getServiceAccountApi, listServiceAccountsApi } from "@/controllers/API/serviceAccount";
import { handleUiRequest, showApiError } from "@/controllers/request";
import type { ServiceAccountItem } from "@/types/api/openApi";
import { formatIsoDateTime } from "@/util/utils";
import { Tabs } from "@bisheng/ui";

import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { OpenApiListFooter } from "../OpenApiList/OpenApiListFooter";
import { useOpenApiList } from "../OpenApiList/useOpenApiList";
import { ApiKeysTab } from "./ApiKeysTab";
import { CreateServiceAccountDialog } from "./CreateServiceAccountDialog";
import { OverviewTab } from "./OverviewTab";
import { ResourceGrantsTab } from "./ResourceGrantsTab";

export function ServiceAccount() {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<ServiceAccountItem | null>(null);
  const [keyword, setKeyword] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [initialTab, setInitialTab] = useState<"overview" | "keys">("overview");
  const [autoOpenIssue, setAutoOpenIssue] = useState(false);

  const fetchPage = useCallback(
    (page: number, pageSize: number) =>
      listServiceAccountsApi({ keyword: searchKeyword || undefined, page, page_size: pageSize }),
    [searchKeyword],
  );
  const list = useOpenApiList(fetchPage);
  const accounts = list.items;
  const idleDays = list.response?.idle_days ?? 0;

  const openDetail = async (id: number, tab: "overview" | "keys" = "overview") => {
    const account = await getServiceAccountApi(id);
    if (account) {
      setInitialTab(tab);
      setAutoOpenIssue(tab === "keys");
      setSelected(account);
    }
  };

  if (selected) {
    const isEnabled = selected.status === "enabled";
    return (
      <div className="h-full min-h-0 flex-1 overflow-y-auto pb-8">
        <div className="mb-4 flex items-center gap-2">
          <Button variant="text" size="small" className="px-1" onClick={() => {
              setSelected(null);
              setAutoOpenIssue(false);
            }} color="default">
            <Outlined.Left aria-hidden="true" className="mr-1 size-4" />
            {t("openApiManagement.actions.back")}
          </Button>
          <h2 className="truncate text-lg font-medium">{selected.name}</h2>
          <span className="text-sm text-muted-foreground">{t(`openApiManagement.status.${selected.status}`)}</span>
        </div>
        <Tabs
          defaultActiveKey={initialTab}
          className="[&>div:first-child]:shrink-0 [&>[role=tabpanel][data-state=active]]:flex [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:flex-1 [&>[role=tabpanel]]:flex-col [&>[role=tabpanel]]:overflow-hidden [&>[role=tabpanel]>div]:mt-2"
          items={[
            {
              key: "overview",
              label: <> {t("openApiManagement.serviceAccount.overview")} </>,
              children: (
                <>
                  {" "}
                  <div>
                    <OverviewTab
                      detail={selected}
                      onChanged={(updated) => {
                        setSelected(updated);
                        void list.reload();
                      }}
                      onDeleted={() => {
                        setSelected(null);
                        void list.reload();
                      }}
                    />
                  </div>
                </>
              ),
            },
            {
              key: "keys",
              label: <> {t("openApiManagement.serviceAccount.keys")} </>,
              children: (
                <>
                  {" "}
                  <div>
                    <ApiKeysTab
                      serviceAccountId={selected.id}
                      accountEnabled={isEnabled}
                      initialIssueOpen={autoOpenIssue}
                      onKeysChanged={() => {
                        void getServiceAccountApi(selected.id).then((updated) => {
                          if (updated) setSelected(updated);
                        }).catch(showApiError);
                        void list.reload();
                      }}
                    />
                  </div>
                </>
              ),
            },
            {
              key: "grants",
              label: <> {t("openApiManagement.serviceAccount.grants")} </>,
              children: (
                <>
                  {" "}
                  <div>
                    <ResourceGrantsTab serviceAccountId={selected.id} serviceAccountName={selected.name} />
                  </div>
                </>
              ),
            },
          ]}
        />
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 flex-1 overflow-y-auto pb-8">
      <div className="mb-4 flex items-center justify-end gap-3">
        <SearchInput value={keyword} placeholder={t("openApiManagement.serviceAccount.search")} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => {
            if (event.key === "Enter") {
              if (keyword.trim() === searchKeyword) void list.reload();
              else setSearchKeyword(keyword.trim());
            }
          }} className={"w-56"} />
        <Button onClick={() => setCreateOpen(true)}>{t("openApiManagement.serviceAccount.create")}</Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("openApiManagement.fields.name")}</TableHead>
            <TableHead>{t("openApiManagement.fields.status")}</TableHead>
            <TableHead>{t("openApiManagement.fields.activeKeys")}</TableHead>
            <TableHead>{t("openApiManagement.fields.owner")}</TableHead>
            <TableHead>{t("openApiManagement.fields.lastUsed")}</TableHead>
            <TableHead>{t("openApiManagement.fields.creator")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {accounts.map((account) => {
            const isEnabled = account.status === "enabled";
            return (
              <TableRow key={account.id}>
                <TableCell>
                  <Button variant="link" className="h-auto max-w-56 px-0 font-medium" onClick={handleUiRequest(() => openDetail(account.id))}>
                    <span className="truncate">{account.name}</span>
                  </Button>
                </TableCell>
                <TableCell>
                  <Tag size="small" dot color={isEnabled ? "success" : "danger"}>
                    {t(isEnabled ? "openApiManagement.status.enabled" : "openApiManagement.status.disabled")}
                  </Tag>
                </TableCell>
                <TableCell>
                  <span className="inline-flex items-center gap-1">
                    <span className={account.active_key_count === 0 ? "text-red-500" : ""}>
                      {account.active_key_count}
                    </span>
                    {account.active_key_count === 0 ? (
                      <SharedTooltip content={t("openApiManagement.serviceAccount.noKeyWarning")}>
                        <span tabIndex={0} className="flex">
                          <Outlined.Question className="size-3.5 shrink-0" />
                        </span>
                      </SharedTooltip>
                    ) : null}
                  </span>
                </TableCell>
                <TableCell>
                  <span className="inline-flex items-center gap-1">
                    <span className={account.resource_owner.disabled ? "text-red-500" : ""}>
                      {account.resource_owner.user_name || account.resource_owner.user_id}
                    </span>
                    {account.resource_owner.disabled ? (
                      <SharedTooltip content={t("openApiManagement.serviceAccount.ownerDisabled")}>
                        <span tabIndex={0} className="flex">
                          <Outlined.Question className="size-3.5 shrink-0" />
                        </span>
                      </SharedTooltip>
                    ) : null}
                  </span>
                </TableCell>
                <TableCell>
                  <span className="inline-flex items-center gap-1">
                    <span>
                      {account.last_used_at
                        ? formatIsoDateTime(account.last_used_at)
                        : t("openApiManagement.serviceAccount.neverUsed")}
                    </span>
                    {account.idle ? (
                      <SharedTooltip content={t("openApiManagement.serviceAccount.idleWarning", { days: idleDays })}>
                        <span tabIndex={0} className="flex">
                          <Outlined.Question className="size-3.5 shrink-0" />
                        </span>
                      </SharedTooltip>
                    ) : null}
                  </span>
                </TableCell>
                <TableCell>
                  <div>{account.creator_name || account.created_by || "-"}</div>
                  <div className="text-xs text-muted-foreground">{formatIsoDateTime(account.create_time)}</div>
                </TableCell>
              </TableRow>
            );
          })}
          {list.isEmpty ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground">
                {t("openApiManagement.empty")}
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
      <OpenApiListFooter
        status={list.status}
        itemCount={accounts.length}
        onLoadMore={list.loadMore}
        onRetry={list.retry}
      />
      <CreateServiceAccountDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(id) => {
          void list.reload();
          void openDetail(id, "keys").catch(showApiError);
        }}
      />
    </div>
  );
}
