import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import Files from "./components/Files";
import Header from "./components/Header";
import Paragraphs from "./components/Paragraphs";
import { useState } from "react";

export default function FilesPage() {
    const [value, setValue] = useState('file')
    const [fileId, setFileId] = useState('')

    const onPreview = (id: string) => {
        setFileId(id)
        setValue('chunk')
    }

    return <div className="size-full px-2 py-4 relative bg-background-login">
        {/* title */}
        <Header />
        {/* tab */}
        <Tabs value={value} onValueChange={(v) => {setValue(v);setFileId('')}} className="mt-4">
            <TabsList className="">
                <TabsTrigger value="file" className="roundedrounded-xl">文件管理</TabsTrigger>
                <TabsTrigger value="chunk">分段管理</TabsTrigger>
            </TabsList>
            <TabsContent value="file">
                <Files onPreview={onPreview} />
            </TabsContent>
            <TabsContent value="chunk">
                <Paragraphs fileId={fileId} />
            </TabsContent>
        </Tabs>
    </div>
};
