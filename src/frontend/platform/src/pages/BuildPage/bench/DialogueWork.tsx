// DialogueWork.tsx
import { useState } from "react";
import LingSiWork from "./LingSiWork";
import Index from "./index";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";

export default function DialogueWork() {
  const [formData, setFormData] = useState(null); // 用于共享数据
  const [defaultValue] = useState("client");

  return (
    <div className="w-full h-full px-2 pt-4 relative">
      <Tabs defaultValue={defaultValue} className="w-full mb-[40px]">
        <TabsList className="">
          <TabsTrigger value="client">日常</TabsTrigger>
          <TabsTrigger value="lingsi" className="roundedrounded-xl">灵思</TabsTrigger>
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