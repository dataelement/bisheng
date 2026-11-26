import {
  Button,
  Pagination,
  SearchInput,
  Select,
  Tag,
  Tooltip,
  TooltipProvider,
  notification,
} from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import {
  getKunlianTenantsSilentApi,
  listAllKunlianApiKeysApi,
  revokeKunlianApiKeyApi,
  rotateKunlianApiKeyApi,
} from "@/controllers/API/kunlianApiKeys";
import { showApiError } from "@/controllers/request";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import type {
  KunlianApiKeyIssued,
  KunlianApiKeyItem,
  KunlianDirectoryTenantItem,
} from "@/types/api/kunlianApiKey";
import { formatIsoDateTime } from "@/util/utils";
import { KeyFormDialog } from "./KeyFormDialog";
import { KeyRevealDialog } from "./KeyRevealDialog";
import {
  getKunlianKeyStatus,
  isAllTenantsScope,
  normalizeUtcIso,
  type KunlianKeyStatus,
} from "./utils";

type StatusFilter = "all" | KunlianKeyStatus;

const DEFAULT_PAGE_SIZE = 10;
const MAX_VISIBLE_TENANTS = 2;
const MAX_VISIBLE_CAPABILITIES = 3;

const STATUS_TAG_COLOR: Record<
  KunlianKeyStatus,
  "success" | "warning" | "danger"
> = {
  active: "success",
  expired: "warning",
  revoked: "danger",
};

export function KunlianApiKey() {
  const { t } = useTranslation();
  const selectLabels = useSelectLabels();
  const paginationLocale = usePaginationLocale();

  const [keys, setKeys] = useState<KunlianApiKeyItem[]>([]);
  const [directoryTenants, setDirectoryTenants] = useState<
    KunlianDirectoryTenantItem[]
  >([]);
  const [loadingList, setLoadingList] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const [formOpen, setFormOpen] = useState(false);
  const [editingKey, setEditingKey] = useState<KunlianApiKeyItem | null>(null);
  const [issuedKey, setIssuedKey] = useState<KunlianApiKeyIssued | null>(null);

  const loadKeys = useCallback(async () => {
    setLoadingList(true);
    try {
      const [items, tenantsResp] = await Promise.all([
        listAllKunlianApiKeysApi(),
        getKunlianTenantsSilentApi(),
      ]);
      setKeys(items);
      if (tenantsResp?.items) {
        setDirectoryTenants(tenantsResp.items);
      }
    } catch (error) {
      showApiError(error);
    } finally {
      setLoadingList(false);
    }
  }, []);

  const tenantMap = useMemo(
    () =>
      new Map(
        directoryTenants.map((item) => [item.external_tenant_id, item]),
      ),
    [directoryTenants],
  );

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  const statusOptions = useMemo(
    () => [
      { value: "all", label: t("kunlianApiKey.filters.statusAll") },
      { value: "active", label: t("kunlianApiKey.status.active") },
      { value: "expired", label: t("kunlianApiKey.status.expired") },
      { value: "revoked", label: t("kunlianApiKey.status.revoked") },
    ],
    [t],
  );

  const filteredKeys = useMemo(() => {
    const query = keyword.trim().toLowerCase();
    return keys.filter((item) => {
      const status = getKunlianKeyStatus(item);
      if (statusFilter !== "all" && status !== statusFilter) {
        return false;
      }
      if (!query) return true;
      return (
        String(item.id).includes(query) ||
        item.key_mask.toLowerCase().includes(query) ||
        item.connection_id.toLowerCase().includes(query) ||
        item.integration_id.toLowerCase().includes(query) ||
        (isAllTenantsScope(item.tenant_ids) &&
          t("kunlianApiKey.scope.allTenantsTag")
            .toLowerCase()
            .includes(query)) ||
        item.tenant_ids.some((tenantId) => {
          const info = tenantMap.get(tenantId);
          return (
            tenantId.toLowerCase().includes(query) ||
            Boolean(info?.name.toLowerCase().includes(query)) ||
            Boolean(info?.code?.toLowerCase().includes(query))
          );
        })
      );
    });
  }, [keys, keyword, statusFilter, tenantMap, t]);

  const totalPages = Math.max(1, Math.ceil(filteredKeys.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pagedKeys = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return filteredKeys.slice(start, start + pageSize);
  }, [filteredKeys, safePage, pageSize]);

  const handleRotate = (item: KunlianApiKeyItem) => {
    bsConfirm({
      title: t("kunlianApiKey.confirm.rotateTitle"),
      desc: t("kunlianApiKey.confirm.rotateDesc", {
        mask: item.key_mask,
      }),
      okTxt: t("kunlianApiKey.actions.rotate"),
      onOk: (close) => {
        setMutating(true);
        return rotateKunlianApiKeyApi(item.id)
          .then(async (rotated) => {
            close();
            if (!rotated) return;
            notification.open({
              type: "success",
              title: String(t("kunlianApiKey.confirm.rotateTitle") ?? ""),
              description: String(t("kunlianApiKey.feedback.rotated") ?? ""),
            });
            setIssuedKey(rotated);
            await loadKeys();
          })
          .finally(() => setMutating(false));
      },
    });
  };

  const handleRevoke = (item: KunlianApiKeyItem) => {
    bsConfirm({
      title: t("kunlianApiKey.confirm.revokeTitle"),
      desc: t("kunlianApiKey.confirm.revokeDesc", {
        mask: item.key_mask,
      }),
      okTxt: t("kunlianApiKey.actions.revoke"),
      onOk: (close) => {
        setMutating(true);
        return revokeKunlianApiKeyApi(item.id)
          .then(async () => {
            close();
            notification.open({
              type: "success",
              title: String(t("kunlianApiKey.confirm.revokeTitle") ?? ""),
              description: String(t("kunlianApiKey.feedback.revoked") ?? ""),
            });
            await loadKeys();
          })
          .finally(() => setMutating(false));
      },
    });
  };

  const renderTenants = (tenantIds: string[]) => {
    if (!tenantIds.length) {
      return <span className="text-muted-foreground">-</span>;
    }
    if (isAllTenantsScope(tenantIds)) {
      return (
        <TooltipProvider delayDuration={100}>
          <Tooltip
            side="top"
            align="start"
            content={t("kunlianApiKey.scope.allTenantsTooltip")}
          >
            <div className="inline-block cursor-default">
              <Tag size="small" color="warning">
                {t("kunlianApiKey.scope.allTenantsTag")}
              </Tag>
            </div>
          </Tooltip>
        </TooltipProvider>
      );
    }
    const visible = tenantIds.slice(0, MAX_VISIBLE_TENANTS);
    const hiddenCount = tenantIds.length - visible.length;
    const formatLabel = (tenantId: string) =>
      tenantMap.get(tenantId)?.name || tenantId;
    const formatTooltipLine = (tenantId: string) => {
      const info = tenantMap.get(tenantId);
      return info ? `${info.name} (${tenantId})` : tenantId;
    };

    const tags = (
      <div className="flex flex-wrap items-center gap-1">
        {visible.map((tenantId) => (
          <Tag key={tenantId} size="small" maxWidth={140}>
            {formatLabel(tenantId)}
          </Tag>
        ))}
        {hiddenCount > 0 ? <Tag size="small">+{hiddenCount}</Tag> : null}
      </div>
    );

    if (hiddenCount <= 0 && !visible.some((id) => tenantMap.has(id))) {
      return tags;
    }

    return (
      <TooltipProvider delayDuration={100}>
        <Tooltip
          side="top"
          align="start"
          content={
            <div className="max-h-56 overflow-y-auto whitespace-pre-line break-all text-left">
              {tenantIds.map(formatTooltipLine).join("\n")}
            </div>
          }
        >
          <div className="inline-block max-w-full cursor-default">{tags}</div>
        </Tooltip>
      </TooltipProvider>
    );
  };

  const renderCapabilities = (item: KunlianApiKeyItem) => {
    if (!item.capabilities.length) {
      return <span className="text-muted-foreground">-</span>;
    }
    const visible = item.capabilities.slice(0, MAX_VISIBLE_CAPABILITIES);
    const hiddenCount = item.capabilities.length - visible.length;
    const content = (
      <div className="flex flex-wrap items-center gap-1">
        {visible.map((capability) => (
          <Tag key={capability} size="small">
            {t(`kunlianApiKey.capabilities.${capability}.label`)}
          </Tag>
        ))}
        {hiddenCount > 0 ? <Tag size="small">+{hiddenCount}</Tag> : null}
      </div>
    );

    if (hiddenCount <= 0) return content;

    return (
      <TooltipProvider delayDuration={100}>
        <Tooltip
          side="top"
          align="start"
          content={
            <div className="whitespace-pre-line text-left">
              {item.capabilities
                .map((capability) =>
                  t(`kunlianApiKey.capabilities.${capability}.label`),
                )
                .join("\n")}
            </div>
          }
        >
          <div className="inline-block max-w-full cursor-default">
            {content}
          </div>
        </Tooltip>
      </TooltipProvider>
    );
  };

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {t("kunlianApiKey.subtitle")}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput
            className="w-64"
            value={keyword}
            clearLabel={t("sharedUi.clear")}
            placeholder={t("kunlianApiKey.filters.searchPlaceholder")}
            onChange={(event) => {
              setKeyword(event.target.value);
              setPage(1);
            }}
          />
          <Select
            {...selectLabels}
            className="w-36"
            value={statusFilter}
            options={statusOptions}
            aria-label={t("kunlianApiKey.filters.statusLabel")}
            onChange={(value) => {
              setStatusFilter((value as StatusFilter) || "all");
              setPage(1);
            }}
          />
          <Button
            type="button"
            variant="outlined"
            color="default"
            disabled={loadingList || mutating}
            onClick={() => void loadKeys()}
          >
            <Outlined.Refresh aria-hidden="true" className="mr-1 size-4" />
            {t("kunlianApiKey.actions.refresh")}
          </Button>
          <Button
            type="button"
            disabled={mutating}
            onClick={() => {
              setEditingKey(null);
              setFormOpen(true);
            }}
          >
            <Outlined.Plus aria-hidden="true" className="mr-1 size-4" />
            {t("kunlianApiKey.actions.issue")}
          </Button>
        </div>
      </div>

      <Table className="min-w-[1160px] table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-44">
              {t("kunlianApiKey.columns.key")}
            </TableHead>
            <TableHead className="w-48">
              {t("kunlianApiKey.columns.connection")}
            </TableHead>
            <TableHead className="w-52">
              {t("kunlianApiKey.columns.tenants")}
            </TableHead>
            <TableHead className="w-56">
              {t("kunlianApiKey.columns.capabilities")}
            </TableHead>
            <TableHead className="w-40">
              {t("kunlianApiKey.columns.expiresAt")}
            </TableHead>
            <TableHead className="w-40">
              {t("kunlianApiKey.columns.createdAt")}
            </TableHead>
            <TableHead className="w-24">
              {t("kunlianApiKey.columns.status")}
            </TableHead>
            <TableHead className="w-44 text-right">
              {t("operations")}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loadingList && keys.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={8}
                className="text-center text-muted-foreground"
              >
                {t("kunlianApiKey.states.loading")}
              </TableCell>
            </TableRow>
          ) : pagedKeys.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={8}
                className="text-center text-muted-foreground"
              >
                {t("kunlianApiKey.states.empty")}
              </TableCell>
            </TableRow>
          ) : (
            pagedKeys.map((item) => {
              const status = getKunlianKeyStatus(item);
              const isRevoked = status === "revoked";
              return (
                <TableRow key={item.id}>
                  <TableCell>
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-1.5">
                        <code className="font-mono text-xs font-medium">
                          {item.key_mask}
                        </code>
                        <span className="text-xs text-muted-foreground">
                          #{item.id}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {t("kunlianApiKey.columns.revision", {
                          revision: item.policy_revision,
                        })}
                        {item.rotated_from_id
                          ? ` · ${t("kunlianApiKey.columns.rotatedFrom", {
                              id: item.rotated_from_id,
                            })}`
                          : ""}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="space-y-0.5">
                      <div className="truncate font-medium" title={item.connection_id}>
                        {item.connection_id}
                      </div>
                      <div
                        className="truncate text-xs text-muted-foreground"
                        title={item.integration_id}
                      >
                        {item.integration_id}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>{renderTenants(item.tenant_ids)}</TableCell>
                  <TableCell>{renderCapabilities(item)}</TableCell>
                  <TableCell className="whitespace-nowrap text-xs">
                    {item.expires_at
                      ? formatIsoDateTime(normalizeUtcIso(item.expires_at))
                      : t("kunlianApiKey.actions.neverExpires")}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs">
                    {formatIsoDateTime(normalizeUtcIso(item.create_time))}
                  </TableCell>
                  <TableCell>
                    <Tag size="small" dot color={STATUS_TAG_COLOR[status]}>
                      {t(`kunlianApiKey.status.${status}`)}
                    </Tag>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    <div className="flex justify-end gap-2">
                      <Button
                        type="button"
                        size="small"
                        variant="link"
                        disabled={mutating || isRevoked}
                        onClick={() => {
                          setEditingKey(item);
                          setFormOpen(true);
                        }}
                      >
                        {t("edit")}
                      </Button>
                      <Button
                        type="button"
                        size="small"
                        variant="link"
                        disabled={mutating || isRevoked}
                        onClick={() => handleRotate(item)}
                      >
                        {t("kunlianApiKey.actions.rotate")}
                      </Button>
                      <Button
                        type="button"
                        size="small"
                        variant="link"
                        color="danger"
                        disabled={mutating || isRevoked}
                        onClick={() => handleRevoke(item)}
                      >
                        {t("kunlianApiKey.actions.revoke")}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>

      <div className="pt-1">
        <Pagination
          current={safePage}
          pageSize={pageSize}
          total={filteredKeys.length}
          showTotal
          showSizeChanger
          locale={paginationLocale}
          onChange={(nextPage, nextPageSize) => {
            setPage(nextPage);
            setPageSize(nextPageSize);
          }}
        />
      </div>

      <KeyFormDialog
        editingKey={editingKey}
        open={formOpen}
        onOpenChange={(nextOpen) => {
          setFormOpen(nextOpen);
          if (!nextOpen) setEditingKey(null);
        }}
        onIssued={(issued) => {
          setFormOpen(false);
          setEditingKey(null);
          setIssuedKey(issued);
          void loadKeys();
        }}
        onUpdated={() => {
          setFormOpen(false);
          setEditingKey(null);
          void loadKeys();
        }}
      />

      <KeyRevealDialog
        issuedKey={issuedKey}
        onClose={() => setIssuedKey(null)}
      />
    </div>
  );
}
