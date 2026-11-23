import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import type { AppItem } from "~/@types/app";
import { getRecommendedAppsApi } from "~/api/apps";
import { writeAppChatOrigin, writeAppChatReturnTo } from "~/pages/appChat/appChatOrigin";
import { AgentCard } from "~/pages/apps/components/AgentCard";
import { generateUUID } from "~/utils";

interface DailyFeaturedAppsProps {
  t: (key: string) => string;
  configuredAppIds?: readonly string[] | null;
}

type FeaturedApp = Omit<AppItem, "description" | "logo" | "user_id" | "flow_type" | "tags"> & {
  description?: string | null;
  logo?: string | null;
  user_id?: string | number | null;
  flow_type?: number;
  type?: number;
  tags?: Array<string | { id?: number; name: string }>;
};

export function DailyFeaturedApps({ t, configuredAppIds }: DailyFeaturedAppsProps) {
  const navigate = useNavigate();
  const appFlowOriginKey = (flowId: string) => `app-flow-origin:${flowId}`;
  const appLastOriginKey = "app-last-origin";

  // A missing field is supported by older config responses; an empty list hides the section.
  const enabled = configuredAppIds === undefined || Boolean(configuredAppIds?.length);
  const { data: dailyApps = [] } = useQuery<AppItem[]>(
    ["recommendedApps", { configuredAppIds }],
    async () => {
      const res = await getRecommendedAppsApi() as { data?: FeaturedApp[] };
      return (res?.data ?? []).flatMap(({ flow_type, type, tags, ...app }) => {
        const flowType = flow_type ?? type;
        if (flowType == null) return [];

        return [{
          ...app,
          description: app.description ?? "",
          logo: app.logo ?? "",
          user_id: String(app.user_id ?? ""),
          flow_type: flowType,
          tags: tags?.map((tag, index) => typeof tag === "string"
            ? { id: index, name: tag }
            : { id: tag.id ?? index, name: tag.name }),
        }];
      });
    },
    { enabled, refetchOnWindowFocus: true },
  );

  const handleCardClick = (agent: AppItem) => {
    const _chatId = generateUUID(32);
    const flowId = agent.id;
    const flowType = agent.flow_type;
    const returnTo = "/apps";
    writeAppChatOrigin(_chatId, "center");
    writeAppChatReturnTo(_chatId, returnTo);
    try {
      sessionStorage.setItem(appFlowOriginKey(String(flowId)), "center");
      sessionStorage.setItem(appLastOriginKey, "center");
    } catch {
      // ignore storage failures
    }
    navigate(
      `/app/${_chatId}/${flowId}/${flowType}?from=center&returnTo=${encodeURIComponent(returnTo)}`,
      {
        state: { appSurfaceReturn: returnTo },
      },
    );
  };

  if (!enabled || dailyApps.length === 0) return null;

  return (
    <div className="relative z-10 w-full pb-24">
      <div className="chat-welcome-apps-header">
        <h3 className="chat-welcome-section-title">{t("dshChat.recommendedApps")}</h3>
      </div>
      <div className="relative max-w-[800px] mx-auto px-4">
        <div className="pr-1">
          {/* Two wide columns on every device: four columns in the 800px area made each card
              about 185px wide against a 142px fixed height, a near-square box whose short
              content left the lower half empty. Height now follows the content. */}
          <div className="chat-welcome-app-grid grid grid-cols-2 gap-3 mb-3">
            {dailyApps.map((app) => (
              <AgentCard key={app.id} agent={app} onStartChat={handleCardClick} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
