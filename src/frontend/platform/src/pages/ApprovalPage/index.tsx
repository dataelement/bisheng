import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Eye, Filter, Pencil, Plus, Trash2, Users } from "lucide-react";
import { toast } from "@/components/bs-ui/toast/use-toast";
import SelectSearch from "@/components/bs-ui/select/select";
import { getRolesApi } from "@/controllers/API/user";
import { Switch } from "@/components/bs-ui/switch";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import {
  createApprovalFlowApi,
  createApprovalNodeApi,
  createApprovalRouteApi,
  createApprovalScenarioApi,
  deleteApprovalFlowApi,
  deleteApprovalNodeApi,
  deleteApprovalRouteApi,
  deleteApprovalScenarioApi,
  listApprovalFlowsApi,
  listApprovalExceptionsApi,
  listApprovalNodesApi,
  listApprovalRoutesApi,
  listApprovalScenarioPresetsApi,
  listApprovalScenariosApi,
  reorderApprovalRoutesApi,
  retryApprovalExceptionApi,
  updateApprovalFlowApi,
  updateApprovalNodeApi,
  updateApprovalRouteApi,
  updateApprovalScenarioApi,
  type ApprovalExceptionItem,
  type ApprovalFlowItem,
  type ApprovalNodeItem,
  type ApprovalRouteItem,
  type ApprovalScenarioItem,
  type ApprovalScenarioPreset,
} from "@/controllers/API/approval";
import { useTranslation } from "react-i18next";

// ─── helpers ────────────────────────────────────────────────────────────────

function StatusBadge({ enabled }: { enabled?: boolean }) {
  return enabled ? (
    <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-green-50 text-green-600 border border-green-200">
      已启用
    </span>
  ) : (
    <span className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-500 border border-gray-200">
      已停用
    </span>
  );
}

function SectionHeader({
  icon,
  title,
  hint,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 py-3">
      <span className="text-text-secondary">{icon}</span>
      <span className="text-sm font-semibold text-text-primary">{title}</span>
      {hint && <span className="text-xs text-text-secondary">{hint}</span>}
      <div className="ml-auto">{action}</div>
    </div>
  );
}

function ActionBtn({
  onClick,
  children,
  variant = "ghost",
  label,
}: {
  onClick: () => void;
  children: React.ReactNode;
  variant?: "ghost" | "primary" | "outline";
  label?: string;
}) {
  const cls =
    variant === "primary"
      ? "inline-flex items-center gap-1 rounded px-3 py-1.5 text-xs bg-primary text-primary-foreground hover:bg-primary/90"
      : variant === "outline"
        ? "inline-flex items-center gap-1 rounded border border-border-subtle px-3 py-1.5 text-xs text-text-primary hover:bg-gray-50"
        : "inline-flex items-center justify-center rounded p-1 text-text-secondary hover:bg-gray-100 hover:text-text-primary";
  return (
    <button type="button" className={cls} onClick={onClick} aria-label={label} title={label}>
      {children}
    </button>
  );
}

// ─── Condition field / value metadata ────────────────────────────────────────

interface ConditionFieldMeta {
  label: string;
  values?: { value: string; label: string }[];
}

// All label strings below are i18n keys resolved with t() at render time.

// Static fixed identity labels (always present regardless of system roles)
const FIXED_ROLE_VALUES = [
  { value: 'admin',        label: 'approvalPage.roleValue.admin' },
  { value: 'tenant_admin', label: 'approvalPage.roleValue.tenant_admin' },
  { value: 'dept_admin',   label: 'approvalPage.roleValue.dept_admin' },
];

// Static menu key options mirroring backend WebMenuResource enum
const MENU_KEY_VALUES = [
  { value: 'workstation',    label: 'approvalPage.menuKeyLabel.workstation' },
  { value: 'admin',          label: 'approvalPage.menuKeyLabel.admin' },
  { value: 'build',          label: 'approvalPage.menuKeyLabel.build' },
  { value: 'create_app',     label: 'approvalPage.menuKeyLabel.create_app' },
  { value: 'knowledge',      label: 'approvalPage.menuKeyLabel.knowledge' },
  { value: 'knowledge_space',label: 'approvalPage.menuKeyLabel.knowledge_space' },
  { value: 'model',          label: 'approvalPage.menuKeyLabel.model' },
  { value: 'tool',           label: 'approvalPage.menuKeyLabel.tool' },
  { value: 'mcp',            label: 'approvalPage.menuKeyLabel.mcp' },
  { value: 'channel',        label: 'approvalPage.menuKeyLabel.channel' },
  { value: 'evaluation',     label: 'approvalPage.menuKeyLabel.evaluation' },
  { value: 'dataset',        label: 'approvalPage.menuKeyLabel.dataset' },
  { value: 'mark_task',      label: 'approvalPage.menuKeyLabel.mark_task' },
  { value: 'board',          label: 'approvalPage.menuKeyLabel.board' },
  { value: 'home',           label: 'approvalPage.menuKeyLabel.home' },
  { value: 'apps',           label: 'approvalPage.menuKeyLabel.apps' },
];

const CONDITION_FIELD_META: Record<string, ConditionFieldMeta> = {
  applicant_role: {
    label: 'approvalPage.condition.applicant_role',
    values: FIXED_ROLE_VALUES,
  },
  menu_key: {
    label: 'approvalPage.condition.menu_key',
    values: MENU_KEY_VALUES,
  },
  space_type: {
    label: 'approvalPage.condition.space_type',
    values: [
      { value: 'public',     label: 'approvalPage.spaceType.public' },
      { value: 'department', label: 'approvalPage.spaceType.department' },
      { value: 'team',       label: 'approvalPage.spaceType.team' },
    ],
  },
};

// Approver source type i18n key map
const APPROVER_SOURCE_LABEL_KEYS: Record<string, string> = {
  direct_user:             'approvalPage.approverSource.direct_user',
  department_admin:        'approvalPage.approverSource.department_admin',
  tenant_admin:            'approvalPage.approverSource.tenant_admin',
  channel_admin:           'approvalPage.approverSource.channel_admin',
  space_admin:             'approvalPage.approverSource.space_admin',
  knowledge_space_owner:   'approvalPage.approverSource.knowledge_space_owner',
  knowledge_space_manager: 'approvalPage.approverSource.knowledge_space_manager',
};

type TFn = (key: string, opts?: Record<string, string>) => string;

function conditionLabel(
  matchConfig: { field?: string; value?: string } | null | undefined,
  t: TFn,
): string {
  if (!matchConfig?.field) return '';
  const meta = CONDITION_FIELD_META[matchConfig.field];
  const fieldLabel = meta
    ? t(meta.label, { defaultValue: matchConfig.field })
    : matchConfig.field;
  const value = matchConfig.value ?? '';
  if (!value) return fieldLabel;
  const staticMatch =
    FIXED_ROLE_VALUES.find((v) => v.value === value) ??
    meta?.values?.find((v) => v.value === value);
  const valLabel = staticMatch
    ? t(staticMatch.label, { defaultValue: staticMatch.value })
    : value.startsWith('role_')
      ? `${t('approvalPage.systemRole', { defaultValue: '系统角色' })} #${value.slice(5)}`
      : value;
  return `${fieldLabel} = ${valLabel}`;
}

// ─── Add/Edit dialogs ────────────────────────────────────────────────────────

function AddScenarioDialog({
  open,
  presets,
  existingCodes,
  onClose,
  onConfirm,
}: {
  open: boolean;
  presets: ApprovalScenarioPreset[];
  existingCodes: Set<string>;
  onClose: () => void;
  onConfirm: (preset: ApprovalScenarioPreset) => void;
}) {
  const { t } = useTranslation("bs");
  const available = useMemo(
    () => presets.filter((p) => !existingCodes.has(p.scenario_code)),
    [presets, existingCodes],
  );
  const [selected, setSelected] = useState("");
  useEffect(() => {
    if (open) setSelected(available[0]?.scenario_code ?? "");
  }, [open, available]);

  const preset = available.find((p) => p.scenario_code === selected) ?? null;

  const conditionFieldLabels = (preset?.condition_fields ?? [])
    .map((f) => t(`approvalPage.condition.${f}`, { defaultValue: f }))
    .join("、");

  const approverSourceLabels = (preset?.approver_source_types ?? [])
    .map((s) => t(APPROVER_SOURCE_LABEL_KEYS[s] ?? `approvalPage.approverSource.${s}`, { defaultValue: s }))
    .join("、");

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("approvalPage.addScenarioTitle", { defaultValue: "新增审批场景" })}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <label className="block text-sm text-text-secondary">
            {t("approvalPage.scenarioNameLabel", { defaultValue: "场景名称" })}
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
            >
              {available.length === 0 && (
                <option value="">{t("approvalPage.allPresetsAdded", { defaultValue: "（所有预置场景已添加）" })}</option>
              )}
              {available.map((p) => (
                <option key={p.scenario_code} value={p.scenario_code}>
                  {p.scenario_name}
                </option>
              ))}
            </select>
          </label>
          {preset && (
            <div className="rounded-lg bg-gray-50 p-3 text-xs text-text-secondary space-y-1.5">
              {conditionFieldLabels && (
                <div>
                  <span className="font-medium text-text-primary">{t("approvalPage.conditionLabel")}：</span>
                  {conditionFieldLabels}
                </div>
              )}
              {approverSourceLabels && (
                <div>
                  <span className="font-medium text-text-primary">{t("approvalPage.approverSourceLabel")}：</span>
                  {approverSourceLabels}
                </div>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-subtle px-4 py-2 text-sm text-text-primary hover:bg-gray-50"
          >
            {t("cancel", { defaultValue: "取消" })}
          </button>
          <button
            type="button"
            disabled={!preset}
            onClick={() => preset && onConfirm(preset)}
            className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-60"
          >
            {t("approvalPage.confirmAdd", { defaultValue: "确认添加" })}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RouteDialog({
  open,
  initial,
  flows,
  conditionFields,
  onClose,
  onConfirm,
}: {
  open: boolean;
  initial: Partial<ApprovalRouteItem>;
  flows: ApprovalFlowItem[];
  conditionFields: string[];
  onClose: () => void;
  onConfirm: (data: {
    route_name: string;
    route_type: string;
    flow_definition_id: number | null;
    match_config: { field?: string; value?: string };
  }) => void;
}) {
  const [name, setName] = useState(initial.route_name ?? "");
  const [type, setType] = useState(initial.route_type ?? "flow");
  const [flowId, setFlowId] = useState(
    initial.flow_definition_id ? String(initial.flow_definition_id) : "",
  );
  const [condField, setCondField] = useState(initial.match_config?.field ?? "");
  const [condValue, setCondValue] = useState(initial.match_config?.value ?? "");
  const [systemRoles, setSystemRoles] = useState<{ value: string; label: string }[]>([]);
  const [roleSearch, setRoleSearch] = useState("");

  useEffect(() => {
    if (open) {
      setName(initial.route_name ?? "");
      setType(initial.route_type ?? "flow");
      setFlowId(initial.flow_definition_id ? String(initial.flow_definition_id) : "");
      setCondField(initial.match_config?.field ?? "");
      setCondValue(initial.match_config?.value ?? "");
      setRoleSearch("");
      // Load system roles for applicant_role condition values
      getRolesApi("").then((res: any) => {
        const list = Array.isArray(res) ? res : (res?.data ?? []);
        setSystemRoles(
          list.map((r: any) => ({
            value: `role_${r.id}`,
            label: r.role_name,
          })),
        );
      }).catch(() => setSystemRoles([]));
    }
  }, [open]);

  const { t } = useTranslation("bs");
  const fieldMeta = condField ? CONDITION_FIELD_META[condField] : null;
  // For applicant_role: merge static fixed labels with dynamically loaded system roles
  // Translate i18n keys to display text here so downstream components receive plain strings
  const allRoleValues = (condField === 'applicant_role'
    ? [...FIXED_ROLE_VALUES, ...systemRoles]
    : (fieldMeta?.values ?? [])
  ).map((v) => ({
    value: v.value,
    label: v.label.startsWith('approvalPage.') ? t(v.label, { defaultValue: v.value }) : v.label,
  }));
  // Apply search filter for applicant_role (search against translated label)
  const effectiveValues = condField === 'applicant_role' && roleSearch
    ? allRoleValues.filter((v) => v.label.toLowerCase().includes(roleSearch.toLowerCase()))
    : allRoleValues;
  const hasEnumValues = allRoleValues.length > 0;

  const handleFieldChange = (f: string) => {
    setCondField(f);
    setCondValue(""); // reset value when field changes
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{initial.id ? "编辑条件分支" : "新增条件分支"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <label className="block text-sm text-text-secondary">
            分支名称
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：管理员直接通过"
              className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
            />
          </label>

          {/* Condition */}
          <div className="rounded-lg border border-border-subtle bg-gray-50 p-3 space-y-3">
            <div className="text-xs font-medium text-text-secondary">匹配条件（从上到下匹配，命中即停止）</div>
            <div className="flex items-center gap-2">
              <select
                value={condField}
                onChange={(e) => handleFieldChange(e.target.value)}
                className="h-9 flex-1 rounded-lg border border-border-subtle bg-white px-2 text-sm text-text-primary outline-none"
              >
                <option value="">无条件（始终命中）</option>
                {conditionFields.map((f) => (
                  <option key={f} value={f}>
                    {CONDITION_FIELD_META[f]
                      ? t(CONDITION_FIELD_META[f].label, { defaultValue: f })
                      : f}
                  </option>
                ))}
              </select>
              {condField && (
                <>
                  <span className="text-xs text-text-secondary">=</span>
                  {hasEnumValues ? (
                    condField === 'applicant_role' ? (
                      // Searchable dropdown for applicant_role (may have many system roles)
                      <div className="flex-1">
                        <SelectSearch
                          value={condValue}
                          options={effectiveValues}
                          selectPlaceholder="请选择"
                          inputPlaceholder="搜索身份 / 角色名…"
                          onValueChange={(v) => setCondValue(v)}
                          onChange={(e) => setRoleSearch(e.target.value)}
                          onOpenChange={() => setRoleSearch("")}
                        />
                      </div>
                    ) : (
                      <select
                        value={condValue}
                        onChange={(e) => setCondValue(e.target.value)}
                        className="h-9 flex-1 rounded-lg border border-border-subtle bg-white px-2 text-sm text-text-primary outline-none"
                      >
                        <option value="">请选择</option>
                        {effectiveValues.map((v) => (
                          <option key={v.value} value={v.value}>
                            {v.label}
                          </option>
                        ))}
                      </select>
                    )
                  ) : (
                    <input
                      value={condValue}
                      onChange={(e) => setCondValue(e.target.value)}
                      placeholder="请输入条件值"
                      className="h-9 flex-1 rounded-lg border border-border-subtle bg-white px-2 text-sm text-text-primary outline-none"
                    />
                  )}
                </>
              )}
            </div>
            {condField && !condValue && (
              <p className="text-xs text-amber-500">请填写条件值，否则该分支将始终命中</p>
            )}
          </div>

          {/* Route type */}
          <label className="block text-sm text-text-secondary">
            处理方式
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
            >
              <option value="pass">无需审批，直接通过</option>
              <option value="flow">进入审批流程</option>
            </select>
          </label>
          {type === "flow" && (
            <label className="block text-sm text-text-secondary">
              绑定审批流程
              <select
                value={flowId}
                onChange={(e) => setFlowId(e.target.value)}
                className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
              >
                <option value="">请选择流程</option>
                {flows.map((f) => (
                  <option key={f.id} value={String(f.id)}>
                    {f.flow_name || f.flow_code}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <DialogFooter>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-subtle px-4 py-2 text-sm text-text-primary hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!name.trim() || (type === "flow" && !flowId)}
            onClick={() =>
              onConfirm({
                route_name: name.trim(),
                route_type: type,
                flow_definition_id: type === "flow" && flowId ? Number(flowId) : null,
                match_config: condField ? { field: condField, value: condValue } : {},
              })
            }
            className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-60"
          >
            保存
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FlowDialog({
  open,
  initial,
  onClose,
  onConfirm,
}: {
  open: boolean;
  initial: Partial<ApprovalFlowItem>;
  onClose: () => void;
  onConfirm: (data: { flow_name: string; flow_code: string }) => void;
}) {
  const [name, setName] = useState(initial.flow_name ?? "");
  const [code, setCode] = useState(initial.flow_code ?? "");
  useEffect(() => {
    if (open) {
      setName(initial.flow_name ?? "");
      setCode(initial.flow_code ?? "");
    }
  }, [open, initial.flow_name, initial.flow_code]);

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{initial.id ? "编辑审批流程" : "新建审批流程"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <label className="block text-sm text-text-secondary">
            流程名称
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：菜单权限审批流程 A"
              className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
            />
          </label>
          <label className="block text-sm text-text-secondary">
            流程编码
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="如：menu_flow_a"
              className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
            />
          </label>
        </div>
        <DialogFooter>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-subtle px-4 py-2 text-sm text-text-primary hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!name.trim() || !code.trim()}
            onClick={() => onConfirm({ flow_name: name.trim(), flow_code: code.trim() })}
            className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-60"
          >
            保存
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// i18n keys for approver source options (same source as APPROVER_SOURCE_LABEL_KEYS)
const APPROVER_SOURCE_OPTIONS = [
  { value: "department_admin",        labelKey: "approvalPage.approverSource.department_admin" },
  { value: "direct_user",             labelKey: "approvalPage.approverSource.direct_user" },
  { value: "knowledge_space_owner",   labelKey: "approvalPage.approverSource.knowledge_space_owner" },
  { value: "knowledge_space_manager", labelKey: "approvalPage.approverSource.knowledge_space_manager" },
];

function NodeDialog({
  open,
  initial,
  onClose,
  onConfirm,
}: {
  open: boolean;
  initial: Partial<ApprovalNodeItem>;
  onClose: () => void;
  onConfirm: (data: {
    node_name: string;
    node_code: string;
    node_mode: string;
    approver_config: Record<string, unknown>;
  }) => void;
}) {
  const [name, setName] = useState(initial.node_name ?? "");
  const [code, setCode] = useState(initial.node_code ?? "");
  const { t } = useTranslation("bs");
  const [mode, setMode] = useState(initial.node_mode ?? "or");
  const [sources, setSources] = useState<{ type: string; label: string }[]>([]);

  const getApproverLabel = (type: string) => {
    const opt = APPROVER_SOURCE_OPTIONS.find((o) => o.value === type);
    return opt ? t(opt.labelKey, { defaultValue: type }) : type;
  };

  useEffect(() => {
    if (open) {
      setName(initial.node_name ?? "");
      setCode(initial.node_code ?? "");
      setMode(initial.node_mode ?? "or");
      const cfg = initial.approver_config as Record<string, unknown> | undefined;
      const rawSources = (cfg?.sources as { type: string; label?: string }[] | undefined) ?? [];
      setSources(
        rawSources.map((s) => ({ type: s.type, label: getApproverLabel(s.type) })),
      );
    }
  }, [open]);

  const addSource = (type: string) => {
    if (sources.some((s) => s.type === type)) return;
    setSources((prev) => [...prev, { type, label: getApproverLabel(type) }]);
  };

  const removeSource = (type: string) => {
    setSources((prev) => prev.filter((s) => s.type !== type));
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{initial.id ? "编辑审批节点" : "新增审批节点"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <label className="block text-sm text-text-secondary">
            节点名称
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：申请人部门管理员审批"
              className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
            />
          </label>
          <label className="block text-sm text-text-secondary">
            节点编码
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="如：dept_admin_review"
              className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
            />
          </label>
          <div className="text-sm text-text-secondary">
            审批人来源
            <div className="mt-1 flex flex-wrap gap-2">
              {sources.map((s) => (
                <span
                  key={s.type}
                  className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-gray-50 px-2 py-0.5 text-xs text-text-primary"
                >
                  {s.label}
                  <button
                    type="button"
                    onClick={() => removeSource(s.type)}
                    className="text-gray-400 hover:text-gray-600"
                  >
                    ×
                  </button>
                </span>
              ))}
              <select
                value=""
                onChange={(e) => e.target.value && addSource(e.target.value)}
                className="h-7 rounded-full border border-dashed border-border-subtle bg-gray-50 px-2 text-xs text-text-secondary outline-none"
              >
                <option value="">＋ 添加审批人</option>
                {APPROVER_SOURCE_OPTIONS.filter((o) => !sources.some((s) => s.type === o.value)).map(
                  (o) => (
                    <option key={o.value} value={o.value}>
                      {t(o.labelKey, { defaultValue: o.value })}
                    </option>
                  ),
                )}
              </select>
            </div>
          </div>
          <label className="block text-sm text-text-secondary">
            节点模式
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="mt-1 block h-10 w-full rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
            >
              <option value="or">或签（任一人同意即通过）</option>
              <option value="and">会签（所有人同意才通过）</option>
            </select>
          </label>
        </div>
        <DialogFooter>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-subtle px-4 py-2 text-sm text-text-primary hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!name.trim() || !code.trim()}
            onClick={() =>
              onConfirm({
                node_name: name.trim(),
                node_code: code.trim(),
                node_mode: mode,
                approver_config: { sources },
              })
            }
            className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-60"
          >
            保存
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function ApprovalPage() {
  const { t } = useTranslation("bs");

  // ── data ──────────────────────────────────────────────────────────────────
  const [presets, setPresets] = useState<ApprovalScenarioPreset[]>([]);
  const [scenarios, setScenarios] = useState<ApprovalScenarioItem[]>([]);
  const [routes, setRoutes] = useState<ApprovalRouteItem[]>([]);
  const [flows, setFlows] = useState<ApprovalFlowItem[]>([]);
  const [nodes, setNodes] = useState<ApprovalNodeItem[]>([]);
  const [exceptions, setExceptions] = useState<ApprovalExceptionItem[]>([]);

  // ── selection ─────────────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<"flow" | "exception">("flow");
  const [selectedScenarioId, setSelectedScenarioId] = useState<number | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState<number | null>(null);

  // ── dialog states ─────────────────────────────────────────────────────────
  const [showAddScenario, setShowAddScenario] = useState(false);
  const [routeDialog, setRouteDialog] = useState<{
    open: boolean;
    initial: Partial<ApprovalRouteItem>;
  }>({ open: false, initial: {} });
  const [flowDialog, setFlowDialog] = useState<{
    open: boolean;
    initial: Partial<ApprovalFlowItem>;
  }>({ open: false, initial: {} });
  const [nodeDialog, setNodeDialog] = useState<{
    open: boolean;
    initial: Partial<ApprovalNodeItem>;
  }>({ open: false, initial: {} });

  // ── exception state ───────────────────────────────────────────────────────
  const [exceptionApproverInputs, setExceptionApproverInputs] = useState<
    Record<number, string>
  >({});

  // ── computed ──────────────────────────────────────────────────────────────
  const selectedScenario = useMemo(
    () => scenarios.find((s) => s.id === selectedScenarioId) ?? null,
    [scenarios, selectedScenarioId],
  );
  const selectedFlow = useMemo(
    () => flows.find((f) => f.id === selectedFlowId) ?? null,
    [flows, selectedFlowId],
  );
  // condition fields available for the selected scenario (from the preset registry)
  const activeConditionFields = useMemo(() => {
    // applicant_role is universal — every scenario supports identity-based routing.
    // Per PRD §5.4.4, all scenarios include 申请人身份 as a condition field.
    const ALWAYS_INCLUDED = ['applicant_role'];
    const dedup = (arr: string[]) => arr.filter((v, i, self) => self.indexOf(v) === i);
    if (!selectedScenario) {
      return dedup([...ALWAYS_INCLUDED, ...Object.keys(CONDITION_FIELD_META)]);
    }
    const preset = presets.find((p) => p.scenario_code === selectedScenario.scenario_code);
    // Filter preset fields by what CONDITION_FIELD_META knows about;
    // then prepend the always-included fields so they appear first.
    const presetFields = preset?.condition_fields?.filter((f) => CONDITION_FIELD_META[f]) ?? [];
    return dedup([...ALWAYS_INCLUDED, ...presetFields]);
  }, [selectedScenario, presets]);
  const existingCodes = useMemo(
    () => new Set(scenarios.map((s) => s.scenario_code)),
    [scenarios],
  );

  // ── data loaders ──────────────────────────────────────────────────────────
  const loadRoutes = async (scenarioId: number) => {
    setRoutes(await listApprovalRoutesApi(scenarioId));
  };

  const loadFlows = async (scenarioId: number, keepFlowId?: number | null) => {
    const list = await listApprovalFlowsApi(scenarioId);
    setFlows(list);
    const nextId =
      keepFlowId != null && list.some((f) => f.id === keepFlowId)
        ? keepFlowId
        : list[0]?.id ?? null;
    setSelectedFlowId(nextId);
    setNodes(nextId ? await listApprovalNodesApi(nextId) : []);
  };

  const selectScenario = async (scenarioId: number) => {
    setSelectedScenarioId(scenarioId);
    await Promise.all([loadRoutes(scenarioId), loadFlows(scenarioId)]);
  };

  const loadPage = async () => {
    const [presetList, scenarioList, exceptionList] = await Promise.all([
      listApprovalScenarioPresetsApi(),
      listApprovalScenariosApi(),
      listApprovalExceptionsApi(),
    ]);
    setPresets(presetList);
    setScenarios(scenarioList);
    setExceptions(exceptionList);
    const initId = selectedScenarioId ?? scenarioList[0]?.id ?? null;
    if (initId) {
      setSelectedScenarioId(initId);
      await Promise.all([loadRoutes(initId), loadFlows(initId, selectedFlowId)]);
    }
  };

  useEffect(() => {
    void loadPage();
  }, []);

  // ── scenario actions ──────────────────────────────────────────────────────
  const handleAddScenario = async (preset: ApprovalScenarioPreset) => {
    try {
      await createApprovalScenarioApi({
        scenario_code: preset.scenario_code,
        scenario_name: preset.scenario_name,
        enabled: false,
      });
      setShowAddScenario(false);
      await loadPage();
    } catch (e: any) {
      toast({ title: "提示", variant: "error", description: String(e || "创建失败") });
    }
  };

  const handleToggleScenario = async (scenario: ApprovalScenarioItem) => {
    try {
      await updateApprovalScenarioApi(scenario.id, { enabled: !scenario.enabled });
      await loadPage();
    } catch (e: any) {
      toast({ title: "提示", variant: "error", description: String(e || "更新失败") });
    }
  };

  const handleDeleteScenario = (scenario: ApprovalScenarioItem) => {
    bsConfirm({
      title: "删除审批场景",
      desc: `确认删除「${scenario.scenario_name}」？已发起的审批实例不受影响`,
      onOk: async (next) => {
        try {
          await deleteApprovalScenarioApi(scenario.id);
          if (selectedScenarioId === scenario.id) setSelectedScenarioId(null);
          await loadPage();
          next();
        } catch (e: any) {
          toast({ title: "提示", variant: "error", description: String(e || "删除失败") });
        }
      },
    });
  };

  // ── route actions ─────────────────────────────────────────────────────────
  const handleSaveRoute = async (data: {
    route_name: string;
    route_type: string;
    flow_definition_id: number | null;
    match_config: { field?: string; value?: string };
  }) => {
    if (!selectedScenarioId) return;
    try {
      const payload = {
        route_name: data.route_name,
        route_type: data.route_type,
        flow_definition_id: data.flow_definition_id,
        match_config: data.match_config,
      };
      if (routeDialog.initial.id) {
        await updateApprovalRouteApi(routeDialog.initial.id, payload);
      } else {
        await createApprovalRouteApi(selectedScenarioId, {
          ...payload,
          sort_order: routes.length,
        });
      }
      setRouteDialog({ open: false, initial: {} });
      await loadRoutes(selectedScenarioId);
    } catch (e: any) {
      toast({ title: "提示", variant: "error", description: String(e || "保存失败") });
    }
  };

  const handleToggleRoute = async (route: ApprovalRouteItem) => {
    try {
      await updateApprovalRouteApi(route.id, {
        route_name: route.route_name,
        route_type: route.route_type,
        flow_definition_id: route.flow_definition_id ?? null,
        enabled: route.enabled === false,
      });
      if (selectedScenarioId) await loadRoutes(selectedScenarioId);
    } catch (e: any) {
      toast({ title: "提示", variant: "error", description: String(e || "更新失败") });
    }
  };

  const handleDeleteRoute = (route: ApprovalRouteItem) => {
    bsConfirm({
      title: "删除条件分支",
      desc: `确认删除分支「${route.route_name}」？`,
      onOk: async (next) => {
        try {
          await deleteApprovalRouteApi(route.id);
          if (selectedScenarioId) await loadRoutes(selectedScenarioId);
          next();
        } catch (e: any) {
          toast({ title: "提示", variant: "error", description: String(e || "删除失败") });
        }
      },
    });
  };

  const moveRoute = async (index: number, direction: "up" | "down") => {
    if (!selectedScenarioId) return;
    const next = [...routes];
    const swapIdx = direction === "up" ? index - 1 : index + 1;
    if (swapIdx < 0 || swapIdx >= next.length) return;
    [next[index], next[swapIdx]] = [next[swapIdx], next[index]];
    try {
      await reorderApprovalRoutesApi(
        selectedScenarioId,
        next.map((r) => r.id),
      );
      await loadRoutes(selectedScenarioId);
    } catch (e: any) {
      toast({ title: "提示", variant: "error", description: String(e || "排序失败") });
    }
  };

  // ── flow actions ──────────────────────────────────────────────────────────
  const handleSaveFlow = async (data: { flow_name: string; flow_code: string }) => {
    if (!selectedScenarioId) return;
    try {
      let newId = flowDialog.initial.id;
      if (newId) {
        await updateApprovalFlowApi(newId, data);
      } else {
        const created = await createApprovalFlowApi(selectedScenarioId, data);
        newId = created.id;
      }
      setFlowDialog({ open: false, initial: {} });
      await loadFlows(selectedScenarioId, newId);
    } catch (e: any) {
      toast({ title: "提示", variant: "error", description: String(e || "保存失败") });
    }
  };

  const handleDeleteFlow = (flow: ApprovalFlowItem) => {
    bsConfirm({
      title: "删除审批流程",
      desc: `确认删除流程「${flow.flow_name}」？`,
      onOk: async (next) => {
        try {
          await deleteApprovalFlowApi(flow.id);
          if (selectedFlowId === flow.id) setSelectedFlowId(null);
          if (selectedScenarioId) await loadFlows(selectedScenarioId);
          next();
        } catch (e: any) {
          toast({ title: "提示", variant: "error", description: String(e || "删除失败") });
        }
      },
    });
  };

  // ── node actions ──────────────────────────────────────────────────────────
  const handleSaveNode = async (data: {
    node_name: string;
    node_code: string;
    node_mode: string;
    approver_config: Record<string, unknown>;
  }) => {
    if (!selectedFlowId) return;
    try {
      if (nodeDialog.initial.id) {
        await updateApprovalNodeApi(nodeDialog.initial.id, data);
      } else {
        await createApprovalNodeApi(selectedFlowId, {
          ...data,
          node_order: nodes.length + 1,
        });
      }
      setNodeDialog({ open: false, initial: {} });
      setNodes(await listApprovalNodesApi(selectedFlowId));
    } catch (e: any) {
      toast({ title: "提示", variant: "error", description: String(e || "保存失败") });
    }
  };

  const handleDeleteNode = (node: ApprovalNodeItem) => {
    bsConfirm({
      title: "删除审批节点",
      desc: `确认删除节点「${node.node_name}」？`,
      onOk: async (next) => {
        try {
          await deleteApprovalNodeApi(node.id);
          if (selectedFlowId) setNodes(await listApprovalNodesApi(selectedFlowId));
          next();
        } catch (e: any) {
          toast({ title: "提示", variant: "error", description: String(e || "删除失败") });
        }
      },
    });
  };

  // ── exception actions ─────────────────────────────────────────────────────
  const handleRetryException = async (
    item: ApprovalExceptionItem,
    payload: { action?: string; approver_user_ids?: number[] } = {},
  ) => {
    try {
      await retryApprovalExceptionApi(item.id, payload);
      toast({ title: "提示", variant: "success", description: "处理成功" });
      setExceptionApproverInputs((c) => ({ ...c, [item.id]: "" }));
      await loadPage();
    } catch (e: any) {
      toast({ title: "提示", variant: "error", description: String(e || "操作失败") });
    }
  };

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-full flex-col bg-background-main-content">
      {/* page header */}
      <div className="border-b border-border-subtle px-6 pt-6 pb-0">
        <h1 className="text-xl font-semibold text-text-primary">审批管理</h1>
        {/* tabs */}
        <div className="mt-4 flex gap-1">
          {(["flow", "exception"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={`rounded-t px-4 py-2 text-sm font-medium transition-colors ${
                activeTab === tab
                  ? "border border-b-0 border-border-subtle bg-white text-primary"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {tab === "flow" ? "流程管理" : "异常流程列表"}
            </button>
          ))}
        </div>
      </div>

      {/* ── 流程管理 tab ─────────────────────────────────────────────────── */}
      {activeTab === "flow" && (
        <div className="flex flex-1 overflow-hidden">
          {/* left: scenario list */}
          <aside className="flex w-[268px] shrink-0 flex-col border-r border-border-subtle bg-white">
            <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
              <span className="text-sm font-semibold text-text-primary">审批场景</span>
              <button
                type="button"
                onClick={() => setShowAddScenario(true)}
                className="inline-flex items-center gap-1 rounded border border-border-subtle px-2.5 py-1 text-xs text-text-primary hover:bg-gray-50"
              >
                <Plus size={12} />
                新增
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {scenarios.map((s) => {
                const active = s.id === selectedScenarioId;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => void selectScenario(s.id)}
                    className={`group relative w-full rounded-lg border px-3 py-3 text-left transition-colors ${
                      active
                        ? "border-primary/30 bg-primary/5"
                        : "border-border-subtle bg-white hover:bg-gray-50"
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <span className="text-sm font-medium text-text-primary leading-snug">
                        {s.scenario_name}
                      </span>
                      <StatusBadge enabled={s.enabled} />
                    </div>
                    {/* action icons — shown on hover */}
                    <div className="mt-2 flex items-center justify-center gap-3 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        type="button"
                        title="编辑"
                        onClick={(e) => {
                          e.stopPropagation();
                          /* scenario name edit not required by spec */
                        }}
                        className="text-gray-400 hover:text-gray-600"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        type="button"
                        title="删除"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteScenario(s);
                        }}
                        className="text-gray-400 hover:text-red-500"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </button>
                );
              })}
              {scenarios.length === 0 && (
                <div className="py-8 text-center text-xs text-text-secondary">
                  暂无审批场景，点击右上角新增
                </div>
              )}
            </div>
          </aside>

          {/* right: scenario detail */}
          <main className="flex flex-1 flex-col overflow-y-auto">
            {!selectedScenario ? (
              <div className="flex flex-1 items-center justify-center text-sm text-text-secondary">
                请在左侧选择一个审批场景
              </div>
            ) : (
              <div className="flex flex-col gap-0">
                {/* scenario header */}
                <div className="flex items-center justify-between border-b border-border-subtle bg-white px-6 py-4">
                  <div className="flex items-center gap-3">
                    <span className="text-base font-semibold text-text-primary">
                      {selectedScenario.scenario_name}
                    </span>
                    <StatusBadge enabled={selectedScenario.enabled} />
                  </div>
                  <div className="flex items-center gap-2 text-sm text-text-secondary">
                    <span>启用</span>
                    <Switch
                      checked={!!selectedScenario.enabled}
                      onCheckedChange={() => void handleToggleScenario(selectedScenario)}
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-px">
                  {/* ── condition branches ─────────────────────────────── */}
                  <div className="bg-white px-6 pt-0 pb-4">
                    <SectionHeader
                      icon={<Filter size={14} />}
                      title="条件分支"
                      hint="从上到下依次校验"
                      action={
                        <ActionBtn
                          variant="outline"
                          onClick={() => setRouteDialog({ open: true, initial: {} })}
                        >
                          <Plus size={12} /> 新增分支
                        </ActionBtn>
                      }
                    />
                    <div className="rounded-lg border border-border-subtle overflow-hidden">
                      {routes.length === 0 && (
                        <div className="py-6 text-center text-xs text-text-secondary">
                          暂无条件分支，点击右上角新增
                        </div>
                      )}
                      {routes.map((route, idx) => {
                        const matchLabel = conditionLabel(route.match_config, t);
                        const flowName = flows.find(
                          (f) => f.id === route.flow_definition_id,
                        )?.flow_name;
                        return (
                          <div
                            key={route.id}
                            className={`flex items-center gap-3 px-4 py-3 ${
                              idx < routes.length - 1 ? "border-b border-border-subtle" : ""
                            }`}
                          >
                            {/* index */}
                            <span className="shrink-0 inline-flex h-5 w-5 items-center justify-center rounded bg-gray-100 text-xs font-medium text-gray-500">
                              {idx + 1}
                            </span>
                            {/* name + condition */}
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium text-text-primary leading-tight">
                                {route.route_name || `分支 #${route.id}`}
                              </div>
                              {matchLabel && (
                                <div className="mt-0.5 text-xs text-text-secondary">
                                  {matchLabel}
                                </div>
                              )}
                            </div>
                            {/* route result */}
                            <div className="shrink-0 flex items-center gap-2">
                              {route.route_type === "pass" ? (
                                <span className="inline-flex items-center gap-1 rounded-full border border-green-200 bg-green-50 px-2.5 py-0.5 text-xs text-green-600">
                                  <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                                  无需审批，直接通过
                                </span>
                              ) : (
                                <div className="flex items-center gap-2">
                                  <span className="text-xs text-text-primary">
                                    {flowName ?? `流程 #${route.flow_definition_id}`}
                                  </span>
                                  <button
                                    type="button"
                                    className="inline-flex items-center gap-1 rounded border border-border-subtle px-2 py-0.5 text-xs text-text-secondary hover:bg-gray-50"
                                  >
                                    <Eye size={11} /> 流程预览
                                  </button>
                                </div>
                              )}
                            </div>
                            {/* toggle + sort + edit + delete */}
                            <div className="shrink-0 flex items-center gap-1.5">
                              <Switch
                                checked={route.enabled !== false}
                                onCheckedChange={() => void handleToggleRoute(route)}
                              />
                              <ActionBtn onClick={() => void moveRoute(idx, "up")}>
                                <ChevronUp size={14} />
                              </ActionBtn>
                              <ActionBtn onClick={() => void moveRoute(idx, "down")}>
                                <ChevronDown size={14} />
                              </ActionBtn>
                              <ActionBtn
                                label="编辑"
                                onClick={() =>
                                  setRouteDialog({
                                    open: true,
                                    initial: route,
                                  })
                                }
                              >
                                <Pencil size={13} />
                              </ActionBtn>
                              <ActionBtn label="删除" onClick={() => handleDeleteRoute(route)}>
                                <Trash2 size={13} className="text-gray-400 hover:text-red-500" />
                              </ActionBtn>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* separator */}
                  <div className="h-2 bg-background-main-content" />

                  {/* ── approval flows ─────────────────────────────────── */}
                  <div className="bg-white px-6 pt-0 pb-6">
                    <SectionHeader
                      icon={<Users size={14} />}
                      title="审批流程"
                      action={
                        <ActionBtn
                          variant="outline"
                          onClick={() => setNodeDialog({ open: true, initial: {} })}
                        >
                          <Plus size={12} /> 新增节点
                        </ActionBtn>
                      }
                    />

                    {/* flow selector row */}
                    <div className="mb-4 flex items-center gap-3">
                      <select
                        value={selectedFlowId ?? ""}
                        onChange={async (e) => {
                          const id = Number(e.target.value) || null;
                          setSelectedFlowId(id);
                          setNodes(id ? await listApprovalNodesApi(id) : []);
                        }}
                        className="h-9 rounded-lg border border-border-subtle bg-white px-3 text-sm text-text-primary outline-none"
                      >
                        <option value="">请选择流程</option>
                        {flows.map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.flow_name || f.flow_code}
                          </option>
                        ))}
                      </select>
                      {selectedFlow && <StatusBadge enabled={selectedFlow.is_active} />}
                      <div className="ml-auto flex items-center gap-2">
                        <ActionBtn
                          variant="outline"
                          onClick={() =>
                            setFlowDialog({
                              open: true,
                              initial: selectedFlow ?? {},
                            })
                          }
                        >
                          {selectedFlow ? "编辑流程" : "新建流程"}
                        </ActionBtn>
                        {selectedFlow && (
                          <ActionBtn onClick={() => handleDeleteFlow(selectedFlow)}>
                            <Trash2 size={13} className="text-gray-400 hover:text-red-500" />
                          </ActionBtn>
                        )}
                      </div>
                    </div>

                    {/* node list */}
                    {!selectedFlowId ? (
                      <div className="rounded-lg border border-dashed border-border-subtle py-8 text-center text-xs text-text-secondary">
                        请先选择或新建一个审批流程
                      </div>
                    ) : nodes.length === 0 ? (
                      <div className="rounded-lg border border-dashed border-border-subtle py-8 text-center text-xs text-text-secondary">
                        暂无节点，点击右上角新增节点
                      </div>
                    ) : (
                      <div className="rounded-lg border border-border-subtle overflow-hidden">
                        {nodes.map((node, idx) => {
                          const sources: { type: string; label: string }[] =
                            (node.approver_config?.sources as any[]) ?? [];
                          return (
                            <div
                              key={node.id}
                              className={`px-4 py-3 ${
                                idx < nodes.length - 1 ? "border-b border-border-subtle" : ""
                              }`}
                            >
                              {/* node header row */}
                              <div className="flex items-center gap-3">
                                <span className="shrink-0 inline-flex h-6 w-6 items-center justify-center rounded-full bg-gray-100 text-xs font-semibold text-gray-600">
                                  {idx + 1}
                                </span>
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm font-medium text-text-primary">
                                    {node.node_name || node.node_code}
                                  </div>
                                  <div className="mt-0.5 text-xs text-text-secondary">
                                    当前节点通过后，才会生成下一节点任务
                                  </div>
                                </div>
                                <div className="shrink-0 flex items-center gap-1.5">
                                  <ActionBtn onClick={() => {}}>
                                    <ChevronUp size={14} />
                                  </ActionBtn>
                                  <ActionBtn onClick={() => {}}>
                                    <ChevronDown size={14} />
                                  </ActionBtn>
                                  <select
                                    value={node.node_mode ?? "or"}
                                    onChange={async (e) => {
                                      await updateApprovalNodeApi(node.id, {
                                        node_mode: e.target.value,
                                      });
                                      if (selectedFlowId)
                                        setNodes(await listApprovalNodesApi(selectedFlowId));
                                    }}
                                    className="h-7 rounded border border-border-subtle bg-white px-2 text-xs text-text-primary outline-none"
                                  >
                                    <option value="or">或签</option>
                                    <option value="and">会签</option>
                                  </select>
                                  <ActionBtn
                                    onClick={() =>
                                      setNodeDialog({ open: true, initial: node })
                                    }
                                  >
                                    <Pencil size={13} />
                                  </ActionBtn>
                                  <ActionBtn onClick={() => handleDeleteNode(node)}>
                                    <Trash2 size={13} className="text-gray-400 hover:text-red-500" />
                                  </ActionBtn>
                                </div>
                              </div>
                              {/* approver chips */}
                              <div className="mt-2 flex flex-wrap items-center gap-2 pl-9">
                                {sources.map((src) => (
                                  <span
                                    key={src.type}
                                    className="inline-flex items-center gap-1 rounded-full border border-border-subtle bg-gray-50 px-2.5 py-0.5 text-xs text-text-primary"
                                  >
                                    <Users size={10} className="text-text-secondary" />
                                    {(() => {
                                      const opt = APPROVER_SOURCE_OPTIONS.find((o) => o.value === src.type);
                                      return opt ? t(opt.labelKey, { defaultValue: src.type }) : (src.label ?? src.type);
                                    })()}
                                  </span>
                                ))}
                                <button
                                  type="button"
                                  onClick={() => setNodeDialog({ open: true, initial: node })}
                                  className="inline-flex items-center gap-1 rounded-full border border-dashed border-border-subtle px-2.5 py-0.5 text-xs text-text-secondary hover:bg-gray-50"
                                >
                                  <Plus size={10} /> 添加审批人
                                  <ChevronDown size={10} />
                                </button>
                                <span className="inline-flex items-center rounded border border-border-subtle bg-gray-50 px-2 py-0.5 text-xs text-text-secondary">
                                  {node.node_mode === "and" ? "会签" : "或签"}
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </main>
        </div>
      )}

      {/* ── 异常流程列表 tab ─────────────────────────────────────────────── */}
      {activeTab === "exception" && (
        <div className="flex-1 overflow-y-auto p-6">
          {exceptions.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-sm text-text-secondary">
              暂无异常流程
            </div>
          ) : (
            <div className="space-y-3">
              {exceptions.map((item) => (
                <div
                  key={item.id}
                  className="rounded-xl border border-border-subtle bg-white p-4"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="text-sm font-medium text-text-primary">
                        {item.exception_type === "route_missing"
                          ? "条件分支未命中"
                          : item.exception_type === "approver_empty"
                            ? "审批人为空"
                            : item.exception_type === "execute_failed"
                              ? "业务执行失败"
                              : item.exception_type}{" "}
                        <span className="ml-1 text-xs text-text-secondary">
                          #{item.id}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-text-secondary">
                        审批实例 #{item.instance_id ?? "--"} · 状态：{item.status ?? "--"} ·{" "}
                        {item.create_time ?? "--"}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <ActionBtn
                        variant="outline"
                        onClick={() => void handleRetryException(item)}
                      >
                        重试
                      </ActionBtn>
                      {item.exception_type === "approver_empty" && (
                        <>
                          <input
                            value={exceptionApproverInputs[item.id] ?? ""}
                            onChange={(e) =>
                              setExceptionApproverInputs((c) => ({
                                ...c,
                                [item.id]: e.target.value,
                              }))
                            }
                            placeholder="输入用户 ID，多个用逗号分隔"
                            className="h-8 rounded-lg border border-border-subtle bg-white px-3 text-xs text-text-primary outline-none"
                          />
                          <ActionBtn
                            variant="outline"
                            onClick={async () => {
                              const ids = (exceptionApproverInputs[item.id] ?? "")
                                .split(",")
                                .map((s) => Number(s.trim()))
                                .filter((n) => n > 0);
                              if (!ids.length) {
                                toast({
                                  title: "提示",
                                  variant: "error",
                                  description: "请输入有效的用户 ID",
                                });
                                return;
                              }
                              await handleRetryException(item, {
                                action: "assign_approvers",
                                approver_user_ids: ids,
                              });
                            }}
                          >
                            指定审批人
                          </ActionBtn>
                          <ActionBtn
                            variant="outline"
                            onClick={() =>
                              void handleRetryException(item, { action: "skip_node" })
                            }
                          >
                            跳过节点
                          </ActionBtn>
                        </>
                      )}
                    </div>
                  </div>
                  {item.detail && Object.keys(item.detail).length > 0 && (
                    <pre className="mt-3 rounded-lg bg-gray-50 p-3 text-xs text-text-secondary overflow-x-auto">
                      {JSON.stringify(item.detail, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Dialogs ─────────────────────────────────────────────────────────── */}
      <AddScenarioDialog
        open={showAddScenario}
        presets={presets}
        existingCodes={existingCodes}
        onClose={() => setShowAddScenario(false)}
        onConfirm={(preset) => void handleAddScenario(preset)}
      />
      <RouteDialog
        open={routeDialog.open}
        initial={routeDialog.initial}
        flows={flows}
        conditionFields={activeConditionFields}
        onClose={() => setRouteDialog({ open: false, initial: {} })}
        onConfirm={(data) => void handleSaveRoute(data)}
      />
      <FlowDialog
        open={flowDialog.open}
        initial={flowDialog.initial}
        onClose={() => setFlowDialog({ open: false, initial: {} })}
        onConfirm={(data) => void handleSaveFlow(data)}
      />
      <NodeDialog
        open={nodeDialog.open}
        initial={nodeDialog.initial}
        onClose={() => setNodeDialog({ open: false, initial: {} })}
        onConfirm={(data) => void handleSaveNode(data)}
      />
    </div>
  );
}
