// DialogueWork.tsx
import { userContext } from "@/contexts/userContext";
import { ScopeBar } from "@/pages/ModelPage/manage/ScopeBar";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AppCenter } from "./AppCenter";
import Index from "./index";
import Subscribe from "./Subscribe";
import KnowledgeSpace from "./KnowledgeSpace";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";

export default function DialogueWork() {
  const [defaultValue] = useState("client");
  const [scopeVersion, setScopeVersion] = useState(0);
  const { t, i18n } = useTranslation();
  const { user } = useContext(userContext) as any;
  useEffect(() => {
    i18n.loadNamespaces('tool');
  }, [i18n]);

  return (
    <div className="w-full h-full px-2 pt-4 relative">
      <Tabs defaultValue={defaultValue} className="w-full mb-[40px]">
        <div className="mb-4 flex items-center gap-3">
          <ScopeBar
            user={user}
            onScopeChange={() => {
              setScopeVersion((value) => value + 1);
            }}
          />
          {/* F035 (PRD §4.8): the 灵思 tab is merged into 首页 (home) — task-mode
              display name / input placeholder live there now, the entry toggle
              moved to role menus, tools share the home pool, and the SOP
              manual library is replaced by skill management. The app-center
              copy moved out into its own 应用 tab. */}
          <TabsList className="">
            <TabsTrigger value="client">{t('bench.home')}</TabsTrigger>
            <TabsTrigger value="knowledgeSpace">{t('bench.knowledgeSpace')}</TabsTrigger>
            <TabsTrigger value="subscribe">{t('bench.subscribe')}</TabsTrigger>
            <TabsTrigger value="appCenter">{t('bench.appCenter')}</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="client" key="client-tab">
          <Index scopeVersion={scopeVersion} />
        </TabsContent>
        <TabsContent value="knowledgeSpace">
          <KnowledgeSpace scopeVersion={scopeVersion} />
        </TabsContent>
        <TabsContent value="subscribe">
          <Subscribe scopeVersion={scopeVersion} />
        </TabsContent>
        <TabsContent value="appCenter">
          <AppCenter scopeVersion={scopeVersion} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
