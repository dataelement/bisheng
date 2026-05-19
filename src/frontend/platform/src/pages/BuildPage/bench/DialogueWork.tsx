// DialogueWork.tsx
import { userContext } from "@/contexts/userContext";
import { ScopeBar } from "@/pages/ModelPage/manage/ScopeBar";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import LingSiWork from "./LingSiWork";
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
          <TabsList className="">
            <TabsTrigger value="client">{t('bench.daily')}</TabsTrigger>
            <TabsTrigger value="lingsi" className="roundedrounded-xl">{t('bench.lingsi')}</TabsTrigger>
            <TabsTrigger value="subscribe">{t('bench.subscribe')}</TabsTrigger>
            <TabsTrigger value="knowledgeSpace">{t('bench.knowledgeSpace')}</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="client" key="client-tab">
          <Index scopeVersion={scopeVersion} />
        </TabsContent>
        <TabsContent value="lingsi">
          <LingSiWork scopeVersion={scopeVersion} />
        </TabsContent>
        <TabsContent value="subscribe">
          <Subscribe scopeVersion={scopeVersion} />
        </TabsContent>
        <TabsContent value="knowledgeSpace">
          <KnowledgeSpace scopeVersion={scopeVersion} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
