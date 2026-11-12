import { Button, notification } from "@bisheng/ui";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { FlowControl } from "@/components/Pro/FlowControl";
import { FlowRadio } from "@/components/Pro/FlowRadio";
import {
  getDepartmentLimitDetailApi,
  saveDepartmentLimitApi,
} from "@/controllers/API/pro";
import { showApiError } from "@/controllers/request";
import type { DepartmentTreeNode } from "@/types/api/department";

type ResourceChanges = Record<
  "assistant" | "skill" | "workFlows",
  Record<string, unknown>[]
>;
const emptyChanges = (): ResourceChanges => ({
  assistant: [],
  skill: [],
  workFlows: [],
});

export function useDepartmentTrafficController(
  dept: DepartmentTreeNode,
  enabled: boolean
) {
  const { t } = useTranslation();
  const [limit, setLimit] = useState(0);
  const [baseline, setBaseline] = useState(0);
  const [changes, setChanges] = useState<ResourceChanges>(emptyChanges);
  const [loading, setLoading] = useState(enabled);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    setChanges(emptyChanges());
    getDepartmentLimitDetailApi(dept.id)
      .then((result: { dept_limit?: number }) => {
        if (cancelled) return;
        setLimit(result.dept_limit ?? 0);
        setBaseline(result.dept_limit ?? 0);
      })
      .catch((error) => {
        if (!cancelled) {
          setFailed(true);
          showApiError(error);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dept.id, enabled, revision]);

  const dirty =
    enabled &&
    (limit !== baseline ||
      Object.values(changes).some((rows) => rows.length > 0));
  const save = useCallback(async () => {
    if (!enabled) return true;
    if (loading || failed) return false;
    if (!dirty) return true;
    await saveDepartmentLimitApi({
      departmentId: dept.id,
      deptLimit: limit,
      ...changes,
    });
    setBaseline(limit);
    setChanges(emptyChanges());
    return true;
  }, [enabled, loading, failed, dirty, dept.id, limit, changes]);
  const handleChange = (
    kind: keyof ResourceChanges,
    rows: Record<string, unknown>[]
  ) =>
    setChanges((previous) => ({
      ...previous,
      [kind]: rows.map((row) => ({ ...row })),
    }));
  return {
    t,
    dept,
    limit,
    setLimit,
    dirty,
    loading,
    failed,
    save,
    handleChange,
    retry: () => setRevision((value) => value + 1),
  };
}

interface DepartmentTrafficViewProps {
  controller: ReturnType<typeof useDepartmentTrafficController>;
}
export function DepartmentTrafficView({
  controller,
}: DepartmentTrafficViewProps) {
  const { t, dept, limit, setLimit, loading, failed, handleChange, retry } =
    controller;
  if (loading)
    return (
      <p role="status" className="py-8 text-sm text-muted-foreground">
        {t("loading")}
      </p>
    );
  if (failed)
    return (
      <div role="alert" className="py-6">
        <p className="mb-3 text-sm">{t("bs:organization.trafficLoadFailed")}</p>
        <Button onClick={retry}>{t("bs:organization.retry")}</Button>
      </div>
    );
  return (
    <div className="space-y-6 pb-2">
      <div>
        <p className="mb-4 text-sm font-medium">
          {t("bs:department.deptFlowControl")}
        </p>
        <FlowRadio limit={limit} onChange={setLimit} />
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          {t("bs:organization.trafficHint")}
        </p>
      </div>
      <FlowControl
        entityId={dept.id}
        entityType="department"
        type={3}
        onChange={(rows) => handleChange("assistant", rows)}
      />
      <FlowControl
        entityId={dept.id}
        entityType="department"
        type={2}
        onChange={(rows) => handleChange("skill", rows)}
      />
      <FlowControl
        entityId={dept.id}
        entityType="department"
        type={5}
        onChange={(rows) => handleChange("workFlows", rows)}
      />
    </div>
  );
}

export function DepartmentTrafficControl({
  dept,
}: {
  dept: DepartmentTreeNode;
}) {
  const controller = useDepartmentTrafficController(dept, true);
  return (
    <div>
      <DepartmentTrafficView controller={controller} />
      <Button
        onClick={() => {
          void controller
            .save()
            .then((saved) => {
              if (saved)
                notification.open({
                  type: "success",
                  title: controller.t("prompt"),
                  description: controller.t("saved"),
                });
            })
            .catch(showApiError);
        }}
      >
        {controller.t("save")}
      </Button>
    </div>
  );
}
