// DialogueWork.tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import LingSiWork from "./LingSiWork";
import Index from "./index";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";

export default function DialogueWork() {
  const { t } = useTranslation();
  const [formData, setFormData] = useState(null); // For sharing data between tabs
  const [defaultValue] = useState("client");

  return (
    <div className="w-full h-full px-2 pt-4 relative">
      <Tabs defaultValue={defaultValue} className="w-full mb-[40px]">
        <TabsList className="">
          <TabsTrigger value="client">{t('bench.daily')}</TabsTrigger>
          <TabsTrigger value="lingsi" className="roundedrounded-xl">{t('bench.lingsi')}</TabsTrigger>
        </TabsList>
        <TabsContent value="client"  key="client-tab">
          <Index formData={formData} setFormData={setFormData} />
        </TabsContent>
        <TabsContent value="lingsi">
          <LingSiWork formData={formData} setFormData={setFormData} />
        </TabsContent>
      </Tabs>
    </div>
  );
}