import { Alert, Button } from '@bisheng/ui';
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { listApprovalNodesApi } from "@/controllers/API/approval";
import { Switch, Tag, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import type { ApproverSource } from "./approvalMetadata";
import { APPROVER_SOURCE_OPTIONS, conditionLabel } from "./approvalMetadata";
import { ActionBtn, SectionHeader, StatusBadge } from "./ApprovalPrimitives";

import type { useApprovalController } from "./useApprovalController";
interface FlowManagementPanelProps {
  controller: ReturnType<typeof useApprovalController>;
}
export function FlowManagementPanel({ controller }: FlowManagementPanelProps) {
  const {
    activeTab,
    t,
    setShowAddScenario,
    scenarios,
    selectedScenarioId,
    selectScenario,
    setEditScenarioDialog,
    handleDeleteScenario,
    selectedScenario,
    handleToggleScenario,
    setRouteDialog,
    routes,
    pageRoleNameMap,
    flows,
    handleFlowPreview,
    handleToggleRoute,
    moveRoute,
    handleDeleteRoute,
    selectedFlowId,
    isNodeEditMode,
    isNodeDirty,
    setIsNodeEditMode,
    setDraftNodes,
    setIsNodeDirty,
    setSelectedFlowId,
    setNodes,
    selectedFlow,
    setNodeDialog,
    cancelNodeEditMode,
    saveNodeChanges,
    setFlowDialog,
    handleDeleteFlow,
    enterNodeEditMode,
    draftNodes,
    nodes,
    moveNode,
    handleDeleteNode,
  } = controller;
  return (
    <>
      {" "}
      {activeTab === "flow" && (
        <div className="flex flex-1 overflow-hidden">
          {/* left: scenario list */}
          <aside className="flex w-[268px] shrink-0 flex-col border-r border-border bg-card">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <span className="text-sm font-semibold text-foreground">{t("approvalPage.scenarioSection")}</span>
              <Button size="small" variant="outlined" type="button" onClick={() => setShowAddScenario(true)} color="default">
                <Outlined.Plus size={12} />
                {t("approvalPage.add")}
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {scenarios.map((s) => {
                const active = s.id === selectedScenarioId;
                return (
                  <div
                    role="button"
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) {
                        event.preventDefault();
                        void selectScenario(s.id);
                      }
                    }}
                    key={s.id}

                    onClick={() => void selectScenario(s.id)}
                    className={`group relative w-full rounded-lg border px-3 py-3 text-left transition-colors ${
                      active
                        ? "border-primary/30 bg-primary/5"
                        : "border-border bg-card hover:bg-gray-50 dark:hover:bg-gray-50/10"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex-1 min-w-0 text-sm font-medium text-foreground leading-snug truncate">
                        {s.scenario_name}
                      </span>
                      <div className="flex items-center gap-1 shrink-0">
                        <StatusBadge enabled={s.enabled} />
                        {/* action icons — shown on hover */}
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
                          <Tooltip content={t("approvalPage.edit")}>
                            <Button size="small" variant="text" aria-label={t("approvalPage.edit")} type="button" iconOnly onClick={(e) => {
                                e.stopPropagation();
                                setEditScenarioDialog({ open: true, scenario: s, name: s.scenario_name });
                              }} color="default">
                              <Outlined.Edit size={13} />
                            </Button>
                          </Tooltip>
                          <Tooltip content={t("approvalPage.delete")}>
                            <Button size="small" variant="text" aria-label={t("approvalPage.delete")} type="button" iconOnly onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteScenario(s);
                              }} color="default">
                              <Outlined.Delete size={13} />
                            </Button>
                          </Tooltip>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
              {scenarios.length === 0 && (
                <div className="py-8 text-center text-xs text-muted-foreground">{t("approvalPage.noScenarios")}</div>
              )}
            </div>
          </aside>

          {/* right: scenario detail */}
          <main className="flex flex-1 flex-col overflow-y-auto">
            {!selectedScenario ? (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                {t("approvalPage.selectScenarioHint")}
              </div>
            ) : (
              <div className="flex flex-col gap-0">
                {/* scenario header */}
                <div className="flex items-center justify-between border-b border-border bg-card px-6 py-4">
                  <div className="flex items-center gap-3">
                    <span className="text-base font-semibold text-foreground">{selectedScenario.scenario_name}</span>
                    <StatusBadge enabled={selectedScenario.enabled} />
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <span>{t("approvalPage.enabled")}</span>
                    <Switch
                      checked={!!selectedScenario.enabled}
                      onCheckedChange={() => void handleToggleScenario(selectedScenario)}
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-px">
                  {/* ── condition branches ─────────────────────────────── */}
                  <div className="bg-card px-6 pt-0 pb-4">
                    <SectionHeader
                      icon={<Outlined.Filter size={14} />}
                      title={t("approvalPage.routeTitle")}
                      hint={t("approvalPage.routeSectionHint")}
                      action={
                        <ActionBtn variant="outline" onClick={() => setRouteDialog({ open: true, initial: {} })}>
                          <Outlined.Plus size={12} /> {t("approvalPage.createRoute")}
                        </ActionBtn>
                      }
                    />
                    <div className="rounded-lg border border-border overflow-hidden">
                      {routes.length === 0 && (
                        <div className="py-6 text-center text-xs text-muted-foreground">
                          {t("approvalPage.noRoutes")}
                        </div>
                      )}
                      {routes.map((route, idx) => {
                        const matchLabel = conditionLabel(route.match_config, t, pageRoleNameMap);
                        const flowName = flows.find((f) => f.id === route.flow_definition_id)?.flow_name;
                        return (
                          <div
                            key={route.id}
                            className={`flex items-center gap-3 px-4 py-3 ${
                              idx < routes.length - 1 ? "border-b border-border" : ""
                            }`}
                          >
                            {/* index */}
                            <span className="shrink-0 inline-flex h-5 w-5 items-center justify-center rounded bg-gray-100 text-xs font-medium text-gray-500 dark:bg-gray-50/10 dark:text-gray-400">
                              {idx + 1}
                            </span>
                            {/* name + condition */}
                            <div className="flex-1 min-w-0">
                              <div className="text-sm font-medium text-foreground leading-tight">
                                {route.route_name || t("subjectSearch.routeNumber", { id: route.id })}
                              </div>
                              {matchLabel && <div className="mt-0.5 text-xs text-muted-foreground">{matchLabel}</div>}
                            </div>
                            {/* route result */}
                            <div className="shrink-0 flex items-center gap-2">
                              {route.route_type === "pass" ? (
                                <Tag size="small" color="success" dot className="shrink-0 whitespace-nowrap">
                                  {t("approvalPage.routeTypePassFull")}
                                </Tag>
                              ) : (
                                <div className="flex items-center gap-2">
                                  <span className="text-xs text-foreground">
                                    {flowName ?? t("subjectSearch.flowNumber", { id: route.flow_definition_id })}
                                  </span>
                                  <Button size="small" variant="outlined" type="button" onClick={() => void handleFlowPreview(route)} color="default">
                                    <Outlined.Eye size={11} /> {t("approvalPage.flowPreview")}
                                  </Button>
                                </div>
                              )}
                            </div>
                            {/* toggle + sort + edit + delete */}
                            <div className="shrink-0 flex items-center gap-1.5">
                              <Switch
                                checked={route.enabled !== false}
                                onCheckedChange={() => void handleToggleRoute(route)}
                              />
                              <ActionBtn label={t("approvalPage.moveUp")} onClick={() => void moveRoute(idx, "up")}>
                                <Outlined.Up size={14} />
                              </ActionBtn>
                              <ActionBtn label={t("approvalPage.moveDown")} onClick={() => void moveRoute(idx, "down")}>
                                <Outlined.Down size={14} />
                              </ActionBtn>
                              <ActionBtn
                                label={t("approvalPage.edit")}
                                onClick={() =>
                                  setRouteDialog({
                                    open: true,
                                    initial: route,
                                  })
                                }
                              >
                                <Outlined.Edit size={13} />
                              </ActionBtn>
                              <ActionBtn label={t("approvalPage.delete")} onClick={() => handleDeleteRoute(route)}>
                                <Outlined.Delete
                                  size={13}
                                  className="text-muted-foreground hover:text-red-500 dark:hover:text-red-400"
                                />
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
                  <div className="bg-card px-6 pt-0 pb-6">
                    <SectionHeader icon={<Outlined.People size={14} />} title={t("approvalPage.flowTitle")} />

                    {/* flow selector + actions row */}
                    <div className="mb-4 flex items-center gap-3">
                      <select
                        value={selectedFlowId ?? ""}
                        onChange={async (e) => {
                          const id = Number(e.target.value) || null;
                          if (isNodeEditMode && isNodeDirty) {
                            bsConfirm({
                              title: t("approvalPage.discardChangesTitle"),
                              desc: t("approvalPage.switchFlowDiscardDesc"),
                              onOk: async (next) => {
                                setIsNodeEditMode(false);
                                setDraftNodes([]);
                                setIsNodeDirty(false);
                                setSelectedFlowId(id);
                                setNodes(id ? await listApprovalNodesApi(id) : []);
                                next();
                              },
                            });
                            return;
                          }
                          setIsNodeEditMode(false);
                          setDraftNodes([]);
                          setIsNodeDirty(false);
                          setSelectedFlowId(id);
                          setNodes(id ? await listApprovalNodesApi(id) : []);
                        }}
                        className="h-9 rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none"
                      >
                        <option value="">{t("approvalPage.selectFlow")}</option>
                        {flows.map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.flow_name || f.flow_code}
                          </option>
                        ))}
                      </select>
                      {selectedFlow && <StatusBadge enabled={selectedFlow.is_active} />}
                      <div className="ml-auto flex items-center gap-2">
                        {isNodeEditMode ? (
                          <>
                            <ActionBtn variant="outline" onClick={() => setNodeDialog({ open: true, initial: {} })}>
                              <Outlined.Plus size={12} /> {t("approvalPage.addNodeBtn")}
                            </ActionBtn>
                            <ActionBtn variant="outline" onClick={cancelNodeEditMode}>
                              {t("approvalPage.cancelEditBtn")}
                            </ActionBtn>
                            <ActionBtn
                              variant="primary"
                              onClick={() => void saveNodeChanges()}
                              className={isNodeDirty ? "" : "opacity-70"}
                            >
                              {t("approvalPage.saveChangesBtn")}
                              {isNodeDirty && (
                                <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-white opacity-80" />
                              )}
                            </ActionBtn>
                          </>
                        ) : (
                          <>
                            {selectedFlow && (
                              <>
                                <ActionBtn
                                  variant="outline"
                                  onClick={() => setFlowDialog({ open: true, initial: selectedFlow })}
                                >
                                  {t("approvalPage.editFlowBtn")}
                                </ActionBtn>
                                <ActionBtn variant="outline" onClick={() => handleDeleteFlow(selectedFlow)}>
                                  {t("approvalPage.deleteFlowBtn")}
                                </ActionBtn>
                                <ActionBtn variant="outline" onClick={enterNodeEditMode}>
                                  <Outlined.Edit size={12} /> {t("approvalPage.editNodesBtn")}
                                </ActionBtn>
                              </>
                            )}
                            <ActionBtn variant="outline" onClick={() => setFlowDialog({ open: true, initial: {} })}>
                              {t("approvalPage.createFlowBtn")}
                            </ActionBtn>
                          </>
                        )}
                      </div>
                    </div>

                    {/* node list */}
                    {!selectedFlowId ? (
                      <div className="rounded-lg border border-dashed border-border py-8 text-center text-xs text-muted-foreground">
                        {t("approvalPage.selectFlowHint")}
                      </div>
                    ) : (
                      (() => {
                        const displayNodes = isNodeEditMode ? draftNodes : nodes;
                        return displayNodes.length === 0 ? (
                          <div className="rounded-lg border border-dashed border-border py-8 text-center text-xs text-muted-foreground">
                            {isNodeEditMode ? (
                              t("approvalPage.noNodes")
                            ) : (
                              <>
                                {t("approvalPage.noNodes")} —{" "}
                                <Button size="small" variant="text" type="button" onClick={enterNodeEditMode} color="default">
                                  {t("approvalPage.editNodesBtn")}
                                </Button>
                              </>
                            )}
                          </div>
                        ) : (
                          <>
                            {isNodeEditMode && (
                              <Alert
                                type="warning"
                                className="mb-3"
                                description={t("approvalPage.nodeEditModeHint")}
                              />
                            )}
                            <div className="rounded-lg border border-border overflow-hidden">
                              {displayNodes.map((node, idx) => {
                                const sources: ApproverSource[] =
                                  (node.approver_config?.sources as ApproverSource[]) ?? [];
                                return (
                                  <div
                                    key={node.id}
                                    className={`px-4 py-3 ${idx < nodes.length - 1 ? "border-b border-border" : ""}`}
                                  >
                                    {/* node header row */}
                                    <div className="flex items-center gap-3">
                                      <span className="shrink-0 inline-flex h-6 w-6 items-center justify-center rounded-full bg-gray-100 text-xs font-semibold text-gray-600 dark:bg-gray-50/10 dark:text-gray-300">
                                        {idx + 1}
                                      </span>
                                      <div className="flex-1 min-w-0">
                                        <div className="text-sm font-medium text-foreground">
                                          {node.node_name || node.node_code}
                                        </div>
                                        <div className="mt-0.5 text-xs text-muted-foreground">
                                          {t("subjectSearch.nextNodeHint")}
                                        </div>
                                      </div>
                                      <div
                                        className={`shrink-0 flex items-center gap-1.5 ${!isNodeEditMode ? "pointer-events-none opacity-40" : ""}`}
                                      >
                                        <ActionBtn
                                          label={t("approvalPage.moveUp")}
                                          disabled={!isNodeEditMode}
                                          onClick={() => void moveNode(idx, "up")}
                                        >
                                          <Outlined.Up size={14} />
                                        </ActionBtn>
                                        <ActionBtn
                                          label={t("approvalPage.moveDown")}
                                          disabled={!isNodeEditMode}
                                          onClick={() => void moveNode(idx, "down")}
                                        >
                                          <Outlined.Down size={14} />
                                        </ActionBtn>
                                        <select
                                          value={node.node_mode ?? "or"}
                                          disabled={!isNodeEditMode}
                                          onChange={(e) => {
                                            if (!isNodeEditMode) return;
                                            setDraftNodes((prev) =>
                                              prev.map((n) =>
                                                n.id === node.id ? { ...n, node_mode: e.target.value } : n,
                                              ),
                                            );
                                            setIsNodeDirty(true);
                                          }}
                                          className="h-7 rounded border border-border bg-background px-2 text-xs text-foreground outline-none"
                                        >
                                          <option value="or">{t("approvalPage.nodeModeOr")}</option>
                                          <option value="and">{t("approvalPage.nodeModeAnd")}</option>
                                        </select>
                                        <ActionBtn
                                          label={t("approvalPage.edit")}
                                          disabled={!isNodeEditMode}
                                          onClick={() => setNodeDialog({ open: true, initial: node })}
                                        >
                                          <Outlined.Edit size={13} />
                                        </ActionBtn>
                                        <ActionBtn
                                          label={t("approvalPage.delete")}
                                          disabled={!isNodeEditMode}
                                          onClick={() => handleDeleteNode(node)}
                                        >
                                          <Outlined.Delete
                                            size={13}
                                            className="text-muted-foreground hover:text-red-500 dark:hover:text-red-400"
                                          />
                                        </ActionBtn>
                                      </div>
                                    </div>
                                    {/* approver chips */}
                                    <div className="mt-2 flex flex-wrap items-center gap-2 pl-9">
                                      {sources.map((src) => {
                                        const userNames: string[] = src.user_names ?? src.userNames ?? [];
                                        if (src.type === "direct_user" && userNames.length > 0) {
                                          return userNames.map((name: string) => (
                                            <Tag
                                              key={`${src.type}-${name}`}
                                              size="small"
                                              icon={<Outlined.People size={12} />}
                                              className="whitespace-nowrap"
                                            >
                                              {name}
                                            </Tag>
                                          ));
                                        }
                                        return (
                                          <Tag
                                            key={src.type}
                                            size="small"
                                            icon={<Outlined.People size={12} />}
                                            className="whitespace-nowrap"
                                          >
                                            {(() => {
                                              const opt = APPROVER_SOURCE_OPTIONS.find((o) => o.value === src.type);
                                              return opt
                                                ? t(opt.labelKey, { defaultValue: src.type })
                                                : (src.label ?? src.type);
                                            })()}
                                          </Tag>
                                        );
                                      })}
                                      {isNodeEditMode && (
                                        <Button size="small" variant="outlined" type="button" onClick={() => setNodeDialog({ open: true, initial: node })} color="default">
                                          <Outlined.Plus size={10} /> {t("approvalPage.addApprover")}
                                          <Outlined.Down size={10} />
                                        </Button>
                                      )}
                                      <Tag size="small" className="shrink-0 whitespace-nowrap">
                                        {node.node_mode === "and"
                                          ? t("approvalPage.nodeModeAnd")
                                          : t("approvalPage.nodeModeOr")}
                                      </Tag>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          </>
                        );
                      })()
                    )}
                  </div>
                </div>
              </div>
            )}
          </main>
        </div>
      )}{" "}
    </>
  );
}
