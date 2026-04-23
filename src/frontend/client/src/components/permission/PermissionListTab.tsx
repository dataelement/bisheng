import { useToastContext, useConfirm } from "~/Providers";
import {
  authorizeResource,
  getGrantableRelationModels,
  getResourcePermissions,
} from "~/api/permission";
import type {
  PermissionEntry,
  RelationLevel,
  ResourceType,
  RelationModel,
} from "~/api/permission";
import { Building2, Loader2, RotateCcw, Trash2, User, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocalize } from "~/hooks";
import { RelationModelOption, RelationSelect } from "./RelationSelect";

const SUBJECT_ICONS = {
  user: User,
  department: Building2,
  user_group: Users,
};

interface PermissionListTabProps {
  resourceType: ResourceType;
  resourceId: string;
  refreshKey: number;
}

const LIST_SUBJECT_TYPES = ["user", "department", "user_group"] as const;
type ListSubjectType = (typeof LIST_SUBJECT_TYPES)[number];

export function PermissionListTab({
  resourceType,
  resourceId,
  refreshKey,
}: PermissionListTabProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const confirm = useConfirm();
  const [entries, setEntries] = useState<PermissionEntry[]>([]);
  const [listTab, setListTab] = useState<ListSubjectType>("user");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [models, setModels] = useState<RelationModelOption[]>([]);

  const mergeGrantableWithEntries = useCallback(
    (grantable: RelationModel[], list: PermissionEntry[]): RelationModelOption[] => {
      const opts: RelationModelOption[] = (grantable || []).map((m) => ({
        id: m.id,
        name: m.is_system ? localize(`com_permission.level_${m.relation}`) : m.name,
        relation: m.relation as RelationLevel,
      }));
      const ids = new Set(opts.map((o) => o.id));
      for (const e of list) {
        if (!e.model_id || ids.has(e.model_id)) continue;
        ids.add(e.model_id);
        opts.push({
          id: e.model_id,
          name: e.model_name || e.relation,
          relation: e.relation as RelationLevel,
        });
      }
      return opts;
    },
    [localize]
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = await getResourcePermissions(resourceType, resourceId);
      if (res) setEntries(res);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [resourceType, resourceId]);

  useEffect(() => { loadData(); }, [loadData, refreshKey]);

  const filteredEntries = useMemo(
    () => entries.filter((e) => e.subject_type === listTab),
    [entries, listTab]
  );

  useEffect(() => { setListTab("user"); }, [resourceId]);

  useEffect(() => {
    getGrantableRelationModels(resourceType, resourceId)
      .then((res) => {
        const merged = mergeGrantableWithEntries(res, entries);
        if (merged.length) setModels(merged);
      })
      .catch(() => {});
  }, [resourceType, resourceId, entries, mergeGrantableWithEntries, refreshKey]);

  const handleModify = async (entry: PermissionEntry, modelId: string) => {
    const model = models.find((m) => m.id === modelId);
    const newLevel = (model?.relation || "viewer") as RelationLevel;
    if (newLevel === entry.relation && (entry.model_id || entry.relation) === modelId) return;
    try {
      await authorizeResource(
        resourceType, resourceId,
        [{
          subject_type: entry.subject_type,
          subject_id: entry.subject_id,
          relation: newLevel,
          model_id: modelId,
          ...(entry.subject_type === "department" ? { include_children: Boolean(entry.include_children) } : {}),
        }],
        [{
          subject_type: entry.subject_type,
          subject_id: entry.subject_id,
          relation: entry.relation,
          ...(entry.subject_type === "department" ? { include_children: Boolean(entry.include_children) } : {}),
        }]
      );
      showToast({ message: localize("com_permission.success_modify"), status: "success" });
      loadData();
    } catch {
      showToast({ message: localize("com_permission.error_revoke_failed"), status: "error" });
    }
  };

  const handleRevoke = async (entry: PermissionEntry) => {
    const ok = await confirm({
      title: localize("com_permission.action_revoke"),
      description: localize("com_permission.confirm_revoke"),
      confirmText: localize("com_permission.action_revoke"),
      cancelText: localize("com_ui_cancel"),
    });
    if (!ok) return;
    try {
      await authorizeResource(
        resourceType, resourceId, [],
        [{
          subject_type: entry.subject_type,
          subject_id: entry.subject_id,
          relation: entry.relation,
          ...(entry.subject_type === "department" ? { include_children: Boolean(entry.include_children) } : {}),
        }]
      );
      showToast({ message: localize("com_permission.success_revoke"), status: "success" });
      loadData();
    } catch {
      showToast({ message: localize("com_permission.error_revoke_failed"), status: "error" });
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12">
        <span className="text-sm text-gray-500">{localize("com_permission.error_permission_denied")}</span>
        <button className="flex items-center gap-1 text-sm text-blue-600 hover:underline" onClick={loadData}>
          <RotateCcw className="h-3.5 w-3.5" /> {localize("com_ui_retry")}
        </button>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-gray-500">
        {localize("com_permission.empty_permissions")}
      </div>
    );
  }

  const subjectLabel = (type: ListSubjectType) => {
    const map: Record<ListSubjectType, string> = {
      user: localize("com_permission.subject_user"),
      department: localize("com_permission.subject_department"),
      user_group: localize("com_permission.subject_user_group"),
    };
    return map[type];
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-1 rounded-md bg-gray-100 p-1 w-fit">
        {LIST_SUBJECT_TYPES.map((st) => (
          <button
            key={st}
            type="button"
            className={`rounded px-3 py-1.5 text-sm transition-colors ${
              listTab === st
                ? "bg-white text-gray-900 shadow"
                : "text-gray-500 hover:text-gray-700"
            }`}
            onClick={() => setListTab(st)}
          >
            {subjectLabel(st)}
          </button>
        ))}
      </div>
      <div className="max-h-[400px] overflow-y-auto">
        {filteredEntries.length === 0 ? (
          <div className="py-10 text-center text-sm text-gray-500">
            {localize("com_permission.list_empty_for_subject")}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-gray-500">
                <th className="w-[40px] py-2"></th>
                <th className="py-2">{subjectLabel(listTab)}</th>
                <th className="w-[140px] py-2">{localize("com_permission.level_viewer")}</th>
                <th className="w-[60px] py-2"></th>
              </tr>
            </thead>
            <tbody>
              {filteredEntries.map((entry, idx) => {
                const Icon = SUBJECT_ICONS[entry.subject_type] || User;
                const isOwner = entry.relation === "owner";
                return (
                  <tr key={`${entry.subject_type}-${entry.subject_id}-${idx}`} className="border-b last:border-0">
                    <td className="py-2">
                      <Icon className="h-4 w-4 text-gray-400" />
                    </td>
                    <td className="py-2 text-sm">
                      {entry.subject_name ?? `${entry.subject_type}:${entry.subject_id}`}
                      {entry.include_children && (
                        <span className="ml-1 text-xs text-gray-400">
                          ({localize("com_permission.include_children")})
                        </span>
                      )}
                    </td>
                    <td className="py-2">
                      {isOwner ? (
                        <span className="text-sm text-gray-500">{localize("com_permission.level_owner")}</span>
                      ) : (
                        <RelationSelect
                          value={entry.model_id || entry.relation}
                          onChange={(v) => handleModify(entry, v)}
                          options={models}
                          className="h-7 w-[110px] text-xs"
                        />
                      )}
                    </td>
                    <td className="py-2">
                      {!isOwner && (
                        <button
                          className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-500"
                          onClick={() => handleRevoke(entry)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
