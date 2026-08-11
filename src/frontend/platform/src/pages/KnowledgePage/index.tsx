import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../../components/bs-ui/tabs";

import { useTranslation } from "react-i18next";
import { useContext } from "react";
import { userContext } from "@/contexts/userContext";
import { FileChangeApprovalSettings } from "./FileChangeApprovalSettings";
import KnowledgeFile from "./KnowledgeFile";
import KnowledgeQa from "./KnowledgeQa";

declare global {
  interface Window {
    LibPage?: { type: string };
  }
}

export function KnowledgePage() {
  const { t } = useTranslation();
  const { user } = useContext(userContext);
  const canManageFileChangeApproval = Boolean(
    user?.role === "admin" || user?.is_global_super || user?.is_child_admin,
  );

  const defaultValue = (() => {
    const page = window.LibPage;
    if (!page) return "file";
    if (page.type === "approval-settings" && !canManageFileChangeApproval)
      return "file";
    return page.type;
  })();

  return (
    <div className="w-full h-full px-2 pt-4 relative">
      <Tabs defaultValue={defaultValue} className="w-full mb-[40px]">
        <TabsList className="">
          <TabsTrigger value="file">{t("lib.fileData")}</TabsTrigger>
          <TabsTrigger value="qa" className="roundedrounded-xl">
            {t("lib.qaData")}
          </TabsTrigger>
          {canManageFileChangeApproval && (
            <TabsTrigger value="approval-settings">
              {t("fileChangeApproval.tab", { ns: "knowledge" })}
            </TabsTrigger>
          )}
        </TabsList>
        <TabsContent value="qa">
          <KnowledgeQa />
        </TabsContent>
        <TabsContent value="file">
          <KnowledgeFile />
        </TabsContent>
        {canManageFileChangeApproval && (
          <TabsContent value="approval-settings">
            <FileChangeApprovalSettings />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

export default KnowledgePage;
