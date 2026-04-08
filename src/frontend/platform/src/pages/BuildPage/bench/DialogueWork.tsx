// DialogueWork.tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import LingSiWork from "./LingSiWork";
import Index from "./index";
import Subscribe from "./Subscribe";
import KnowledgeSpace from "./KnowledgeSpace";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";

export default function DialogueWork() {
  const [defaultValue] = useState("client");
  const { t, i18n } = useTranslation();
  useEffect(() => {
    i18n.loadNamespaces('tool');
  }, [i18n]);

  return (
    <div className="w-full h-full px-2 pt-4 relative">
      <Tabs defaultValue={defaultValue} className="w-full mb-[40px]">
        <TabsList className="">
          <TabsTrigger value="client">{t('bench.daily')}</TabsTrigger>
          <TabsTrigger value="lingsi" className="roundedrounded-xl">{t('bench.lingsi')}</TabsTrigger>
          <TabsTrigger value="subscribe">{t('bench.subscribe')}</TabsTrigger>
          <TabsTrigger value="knowledgeSpace">{t('bench.knowledgeSpace')}</TabsTrigger>
        </TabsList>
        <TabsContent value="client" key="client-tab">
          <Index />
        </TabsContent>
        <TabsContent value="lingsi">
          <LingSiWork />
        </TabsContent>
        <TabsContent value="subscribe">
          <Subscribe />
        </TabsContent>
        <TabsContent value="knowledgeSpace">
          <KnowledgeSpace />
        </TabsContent>
      </Tabs>
    </div>
  );
}