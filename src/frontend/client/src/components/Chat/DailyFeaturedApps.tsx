import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { getRecommendedAppsApi } from "~/api/apps";
import { writeAppChatOrigin, writeAppChatReturnTo } from "~/pages/appChat/appChatOrigin";
import { generateUUID } from "~/utils";
import { Card, CardContent } from "../ui/Card";
import AppAvator from "../Avator";

interface DailyFeaturedAppsProps {
  t: (key: string) => string;
}

type FeaturedApp = {
  id: string;
  name: string;
  description?: string;
  logo?: string;
  flow_type?: number;
  type?: number;
  tags?: Array<string | { id?: number; name: string }>;
};

export function DailyFeaturedApps({ t }: DailyFeaturedAppsProps) {
  const navigate = useNavigate();
  const appFlowOriginKey = (flowId: string) => `app-flow-origin:${flowId}`;
  const appLastOriginKey = "app-last-origin";

  const { data: dailyApps = [] } = useQuery<FeaturedApp[]>(
    ["recommendedApps"],
    async () => {
      const res = await getRecommendedAppsApi() as { data?: FeaturedApp[] };
      return res?.data ?? [];
    },
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false },
  );

  const handleCardClick = (agent: FeaturedApp) => {
    const _chatId = generateUUID(32);
    const flowId = agent.id;
    const flowType = agent.flow_type || agent.type;
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
  const displayApps = dailyApps;

  if (dailyApps.length === 0) return null;

  return (
    <div className="relative z-10 w-full pb-24">
      <div className="flex justify-between items-center mb-3 text-sm text-gray-500 max-w-[800px] mx-auto px-4">
        <h2 className="text-sm text-gray-400">{t("dshChat.recommendedApps")}</h2>
      </div>
      <div className="relative max-w-[800px] mx-auto px-4">
        <div className="pr-1">
          <div className="grid grid-cols-2 touch-desktop:grid-cols-4 gap-3 mb-3">
            {displayApps.map((appItem) => (
              <Card
                key={appItem.id}
                className="group flex flex-col py-0 rounded-lg shadow-[0_2px_4px_rgba(0,0,0,0.02)] border border-border-base overflow-hidden cursor-pointer hover:border-blue-500 hover:shadow-[0_4px_14px_rgb(var(--brand-500)/0.12)] transition-all duration-300 h-[142px] hover:-translate-y-1"
                style={{
                  background:
                    "linear-gradient(135deg, rgb(var(--brand-500)/0.04) 0%, #fff 50%, rgb(var(--brand-500)/0.04) 100%)",
                }}
                onClick={() => handleCardClick(appItem)}
              >
                <CardContent className="h-full p-2 flex flex-col relative w-full">
                  <div className="flex items-center gap-2.5 mb-2 shrink-0">
                    <AppAvator
                      id={appItem.name}
                      url={appItem.logo}
                      flowType={appItem.flow_type || appItem.type}
                      className={`size-[32px] min-w-[32px] !rounded-lg`}
                      iconClassName="w-5 h-5"
                    />
                    <div className="text-[15px] font-medium text-text-1 line-clamp-1 break-all">
                      {appItem.name}
                    </div>
                  </div>
                  <div className="text-[13px] text-text-3 line-clamp-2 break-all font-normal leading-[1.5]">
                    {appItem.description}
                  </div>

                  <div className="mt-auto pt-2 relative h-[30px] shrink-0 w-full overflow-hidden">
                    <div className="absolute inset-x-0 bottom-0 top-1 flex gap-1.5 flex-wrap overflow-hidden opacity-100 fine-pointer:group-hover:opacity-0 transition-opacity duration-200 pointer-events-none coarse-pointer:opacity-0">
                      {appItem.tags &&
                        appItem.tags.map((tag) => (
                          <div
                            key={typeof tag === "string" ? tag : tag.id || tag.name}
                            className="bg-fill-2 text-text-2 text-[12px] px-2 py-[2px] rounded-[4px] font-normal whitespace-nowrap"
                          >
                            {typeof tag === "string" ? tag : tag.name}
                          </div>
                        ))}
                    </div>
                    <div className="absolute inset-x-0 bottom-0 top-1 flex items-center justify-center bg-blue-500 rounded-md text-white text-[13px] font-medium opacity-0 fine-pointer:group-hover:opacity-100 transform translate-y-2 fine-pointer:group-hover:translate-y-0 transition-all duration-300 coarse-pointer:opacity-100 coarse-pointer:translate-y-0">
                      {t("com_app_start_chat")}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
