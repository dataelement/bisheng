import { useState } from "react";
import { Button, Tabs, Tooltip, notification } from "@bisheng/ui";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/bs-ui/dialog";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { showApiError } from "@/controllers/request";
import { unmountTenantApi } from "@/controllers/API/department";
import { isGuestDepartmentDeptId } from "@/pages/DepartmentPage/constants/systemDepartments";
import type { DepartmentTreeNode } from "@/types/api/department";
import { useDepartmentSettingsController } from "./DepartmentSettings";
import { DepartmentSettingsView } from "./DepartmentSettingsView";
import {
  DepartmentTrafficView,
  useDepartmentTrafficController,
} from "./DepartmentTrafficControl";

interface DepartmentSettingsDialogProps {
  dept: DepartmentTreeNode;
  showTrafficControl: boolean;
  onChanged: (removedDeptId?: string) => void;
  onClose: () => void;
  onMarkAsTenant?: (deptId: number, deptName: string) => void;
}

export function DepartmentSettingsDialog({
  dept,
  showTrafficControl,
  onChanged,
  onClose,
  onMarkAsTenant,
}: DepartmentSettingsDialogProps) {
  const settings = useDepartmentSettingsController({
    dept,
    onChanged,
    onMarkAsTenant,
  });
  const traffic = useDepartmentTrafficController(
    dept,
    showTrafficControl && dept.status !== "archived"
  );
  const { t, isArchived } = settings;
  const [tab, setTab] = useState("basic");
  const [saving, setSaving] = useState(false);
  const [partiallySaved, setPartiallySaved] = useState(false);
  const dirty = settings.hasUnsavedSettingsChanges() || traffic.dirty;
  const handleLeave = (leave = onClose) => {
    if (saving) return;
    const finishLeave = () => {
      if (partiallySaved || settings.hasCommittedChanges) onChanged();
      leave();
    };
    if (!dirty) {
      finishLeave();
      return;
    }
    bsConfirm({
      title: t("prompt"),
      desc: t("bs:organization.discardChanges"),
      onOk(next) {
        finishLeave();
        next();
      },
    });
  };
  const handleSave = async () => {
    setSaving(true);
    let basicsSaved = false;
    try {
      if (!(await settings.handleGlobalSave(true))) {
        setTab("basic");
        return;
      }
      basicsSaved = true;
      if (!(await traffic.save())) {
        setTab("traffic");
        setPartiallySaved(true);
        return;
      }
      notification.open({
        type: "success",
        title: t("prompt"),
        description: t("saved"),
      });
      onChanged();
      onClose();
    } catch (error) {
      if (basicsSaved) {
        setPartiallySaved(true);
        setTab("traffic");
      }
      showApiError(error);
    } finally {
      setSaving(false);
    }
  };
  const canArchive =
    !isArchived &&
    !settings.isSynced &&
    dept.parent_id !== null &&
    !isGuestDepartmentDeptId(dept.dept_id);
  const canMount = onMarkAsTenant && dept.parent_id !== null;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) handleLeave();
      }}
    >
      <DialogContent
        className="flex max-h-[85vh] flex-col gap-0 sm:max-w-[640px]"
        onPointerDownOutside={(event) => event.preventDefault()}
      >
        <DialogHeader className="shrink-0 pb-4">
          <DialogTitle>{t("bs:department.settings")}</DialogTitle>
          <DialogDescription className="sr-only">{dept.name}</DialogDescription>
        </DialogHeader>
        {showTrafficControl && !isArchived && (
          <Tabs
            activeKey={tab}
            onChange={setTab}
            className="mb-4 shrink-0"
            items={[
              { key: "basic", label: t("bs:department.sectionBasic") },
              { key: "traffic", label: t("bs:department.trafficControl") },
            ]}
          />
        )}
        <fieldset
          disabled={saving}
          aria-busy={saving}
          className="min-h-0 min-w-0 flex-1 overflow-y-auto border-0 p-0 pr-1"
          onPointerDownCapture={(event) => {
            if (saving) {
              event.preventDefault();
              event.stopPropagation();
            }
          }}
          onKeyDownCapture={(event) => {
            if (saving) {
              event.preventDefault();
              event.stopPropagation();
            }
          }}
        >
          {settings.partialBasicSave ? (
            <p role="alert" className="mb-4 text-sm text-destructive">
              {t("bs:organization.partialBasicSave")}
            </p>
          ) : (
            partiallySaved && (
              <p role="alert" className="mb-4 text-sm text-destructive">
                {t("bs:organization.partialSave")}
              </p>
            )
          )}
          <div hidden={tab !== "basic"}>
            <DepartmentSettingsView
              controller={{ ...settings, FORM_CONTROL_WIDTH: "w-full" }}
              hideActions
            />
          </div>
          {showTrafficControl && !isArchived && (
            <div hidden={tab !== "traffic"}>
              <DepartmentTrafficView controller={traffic} />
            </div>
          )}
        </fieldset>
        <DialogFooter className="mt-4 flex-wrap items-center gap-2 border-t pt-4 sm:justify-between">
          <div className="flex flex-wrap gap-2">
            {isArchived ? (
              <>
                <Button
                  variant="outlined"
                  color="default"
                  onClick={settings.handleRestore}
                >
                  {t("bs:department.restore")}
                </Button>
                {!isGuestDepartmentDeptId(dept.dept_id) && (
                  <Button
                    variant="text"
                    color="danger"
                    onClick={settings.handlePurge}
                  >
                    {t("bs:department.permanentDelete")}
                  </Button>
                )}
              </>
            ) : (
              <>
                {canMount && (
                  <Button
                    variant="outlined"
                    color="default"
                    disabled={saving}
                    onClick={() =>
                      handleLeave(() => {
                        if (dept.is_tenant_root) {
                          bsConfirm({
                            title: t("bs:tenant.unmountTitle"),
                            desc: t("bs:tenant.unmountConfirm"),
                            onOk: async (next) => {
                              await unmountTenantApi(dept.id);
                              onChanged();
                              onClose();
                              next();
                            },
                          });
                        } else {
                          onClose();
                          onMarkAsTenant?.(dept.id, dept.name);
                        }
                      })
                    }
                  >
                    {t(
                      dept.is_tenant_root
                        ? "bs:tenant.unmount"
                        : "bs:tenant.markAsTenant"
                    )}
                  </Button>
                )}
              </>
            )}
          </div>
          <div className="flex gap-2">
            {canArchive && (
              <Tooltip content={t("bs:organization.archiveHint")}>
                <span>
                  <Button
                    variant="outlined"
                    color="default"
                    disabled={saving}
                    onClick={() => handleLeave(settings.handleDelete)}
                  >
                    {t("bs:organization.archive")}
                  </Button>
                </span>
              </Tooltip>
            )}
            <Button
              variant="outlined"
              color="default"
              disabled={saving}
              onClick={() => handleLeave()}
            >
              {t("cancel")}
            </Button>
            {!isArchived && (
              <Button
                disabled={saving || settings.loading || traffic.loading}
                onClick={() => void handleSave()}
              >
                {t(saving ? "loading" : "save")}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
