import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../../components/bs-ui/tabs";

import { useTranslation } from "react-i18next";
import KnowledgeFile from "./KnowledgeFile";
import KnowledgeQa from "./KnowledgeQa";

declare global {
  interface Window {
    LibPage?: { type: string };
  }
}

export function KnowledgePage() {
  const { t } = useTranslation();

  const defaultValue = (() => {
    const page = window.LibPage;
    if (!page) return "file";
    return page.type === "qa" ? "qa" : "file";
  })();

  return (
    <div className="w-full h-full px-2 pt-4 relative">
      <Tabs defaultValue={defaultValue} className="w-full mb-[40px]">
        <TabsList className="">
          <TabsTrigger value="file">{t("lib.fileData")}</TabsTrigger>
          <TabsTrigger value="qa" className="roundedrounded-xl">
            {t("lib.qaData")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="qa">
          <KnowledgeQa />
        </TabsContent>
        <TabsContent value="file">
          <KnowledgeFile />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default KnowledgePage;
