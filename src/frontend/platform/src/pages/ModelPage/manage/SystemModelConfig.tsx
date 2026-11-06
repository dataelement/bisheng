// @ts-strict-ignore
import { Outlined } from "bisheng-icons";
import { Button, Tabs, Tooltip } from "@bisheng/ui";
import { userContext } from "@/contexts/userContext";
import { getTenantsApi } from "@/controllers/API/tenant";
import { useAdminScope } from "@/hooks/useAdminScope";
import { Tenant } from "@/types/api/tenant";

import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { isGlobalSuperUser } from "./permissions";
import { isSpeechModelType } from "./speechConfig";
import { ScopeBanner } from "./SystemConfigBanners";
import AssisModel from "./tabs/AssisModel";
import EvaluationModel from "./tabs/EvaluationModel";
import { KnowledgeModel } from "./tabs/KnowledgeModel";
import WorkflowModel from "./tabs/WorkflowModel";
import WorkbenchModel from "./tabs/WorkbenchModel";

const ROOT_TENANT_ID = 1;

export default function SystemModelConfig({
  data,
  defaultTab,
  onBack,
  onTabChange,
}: {
  data: any;
  defaultTab?: string;
  onBack: () => void;
  onTabChange?: (tab: string) => void;
}) {
  const { t } = useTranslation("model");
  const { user } = useContext(userContext) as any;
  const isGlobalSuper = isGlobalSuperUser(user);
  const [activeTab, setActiveTab] = useState(
    defaultTab === "desktop" ? "workbench" : defaultTab || "workbench",
  );
  // useAdminScope's GET /admin/tenant-scope returns HTTP 403 + 19701 for
  // non-super callers (INV-T14). GET /tenants is also super-only
  // (get_admin_user). Both are only needed by ScopeBanner / childTenant
  // when a super admin switches management view; Child Admins never see
  // a scope switcher and only ever look at their own tenant. Gate both
  // calls so Child Admins do not trip the request.ts 403→/403 redirect.
  const { scope } = useAdminScope({ enabled: isGlobalSuper });
  const [tenants, setTenants] = useState<Tenant[]>([]);

  useEffect(() => {
    setActiveTab(defaultTab === "desktop" ? "workbench" : defaultTab || "workbench");
  }, [defaultTab]);

  useEffect(() => {
    if (!isGlobalSuper) {
      return;
    }
    let cancelled = false;
    getTenantsApi({ page: 1, page_size: 100, status: "active" })
      .then((res) => {
        if (!cancelled) setTenants(res?.data || []);
      })
      .catch(() => {
        if (!cancelled) setTenants([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isGlobalSuper]);

  const rootTenant = useMemo(() => tenants.find((row) => row.id === ROOT_TENANT_ID) || null, [tenants]);
  const childTenant = useMemo(() => {
    if (scope.scope_tenant_id === null || scope.scope_tenant_id === ROOT_TENANT_ID) return null;
    return tenants.find((row) => row.id === scope.scope_tenant_id) || null;
  }, [scope.scope_tenant_id, tenants]);

  const { llmOptions, embeddings, asrModel } = useMemo(() => {
    const llmOptions = [];
    const embeddings = [];
    const asrModel = [];
    const ttsModel = [];
    const rerank = [];
    data.forEach((server) => {
      const serverEmbItem = { value: server.id, label: server.name, children: [] };
      const serverLlmItem = { value: server.id, label: server.name, children: [] };
      const serverAsrItem = { value: server.id, label: server.name, children: [] };
      const serverTtsItem = { value: server.id, label: server.name, children: [] };
      const rerankItem = { value: server.id, label: server.name, children: [] };

      server.models.forEach((model) => {
        const item = {
          value: model.id,
          label: model.model_name,
        };
        if (!model.online) return;
        if (isSpeechModelType(model.model_type)) {
          serverAsrItem.children.push(item);
        } else if (model.model_type === "tts") {
          serverTtsItem.children.push(item);
        } else if (model.model_type === "embedding") {
          serverEmbItem.children.push(item);
        } else if (model.model_type === "llm") {
          serverLlmItem.children.push(item);
        } else {
          rerankItem.children.push(item);
        }
      });

      if (serverLlmItem.children.length) llmOptions.push(serverLlmItem);
      if (serverEmbItem.children.length) embeddings.push(serverEmbItem);
      if (serverAsrItem.children.length) asrModel.push(serverAsrItem);
      if (serverTtsItem.children.length) ttsModel.push(serverTtsItem);
      if (rerankItem.children.length) rerank.push(rerankItem);
    });

    return { llmOptions, embeddings, asrModel, ttsModel, rerank };
  }, [data]);

  return (
    <div className="px-2 py-4 size-full pb-20 relative overflow-y-auto">
      <div className="">
        <div className="flex ml-6 items-center gap-x-3">
          <Tooltip content={t("back", { ns: "bs" })} side="right">
            <Button variant="ghost" size="icon" aria-label={t("back", { ns: "bs" })} onClick={onBack}>
              <Outlined.ArrowLeft />
            </Button>
          </Tooltip>
          <span>{t("model.systemModelSettings")}</span>
        </div>
        <div className="px-4">
          {activeTab !== "desktop" && (
            <ScopeBanner
              isGlobalSuper={isGlobalSuper}
              scopeTenantId={scope.scope_tenant_id ?? null}
              rootTenant={rootTenant}
              childTenant={childTenant}
            />
          )}
          <Tabs
            className="[&_[role=tablist]]:px-4"
            activeKey={activeTab}
            onChange={(tab) => {
              setActiveTab(tab);
              onTabChange?.(tab);
            }}
            items={[
              {
                key: "workbench",
                label: t("model.userSelectableModels"),
                children: (
                  <WorkbenchModel
                    data={data}
                    onBack={onBack}
                  />
                ),
              },
              {
                key: "knowledge",
                label: t("model.knowledgeBaseModel"),
                children: (
                  <KnowledgeModel
                    llmOptions={llmOptions}
                    embeddings={embeddings}
                    asrModel={asrModel}
                    onBack={onBack}
                  />
                ),
              },
              {
                key: "assis",
                label: t("model.assistantModel"),
                children: <AssisModel llmOptions={llmOptions} onBack={onBack} />,
              },
              {
                key: "evaluation",
                label: t("model.evaluationModel"),
                children: <EvaluationModel llmOptions={llmOptions} onBack={onBack} />,
              },
              {
                key: "workflow",
                label: t("model.workflowModel"),
                children: <WorkflowModel llmOptions={llmOptions} onBack={onBack} />,
              },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
