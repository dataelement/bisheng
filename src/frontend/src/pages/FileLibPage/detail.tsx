import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useState } from "react";
import Files from "./components/Files";
import Header from "./components/Header";
import Paragraphs from "./components/Paragraphs";

export default function FilesPage() {
    const [value, setValue] = useState('file')
    const [fileId, setFileId] = useState('')

    const onPreview = (id: string) => {
        setFileId(id)
        setValue('chunk')
    }

    return <div className="size-full px-2 py-4 relative bg-background-login">
        {/* tab */}
        <Tabs value={value} onValueChange={(v) => { setValue(v); setFileId('') }}>
            <div className="flex justify-between w-1/2">
                {/* title */}
                <Header />
                <TabsList>
                    <TabsTrigger value="file" className="roundedrounded-xl">文件管理</TabsTrigger>
                    <TabsTrigger value="chunk">分段管理</TabsTrigger>
                </TabsList>
            </div>
            <TabsContent value="file">
                <Files onPreview={onPreview} />
            </TabsContent>
            <TabsContent value="chunk">
                <Paragraphs fileId={fileId} />
            </TabsContent>
        </Tabs>
    </div>
};
