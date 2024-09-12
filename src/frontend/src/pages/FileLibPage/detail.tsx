import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useState } from "react";
import Files from "./components/Files";
import Header from "./components/Header";
import Paragraphs from "./components/Paragraphs";
import { useTranslation } from "react-i18next";

export default function FilesPage() {
    const [value, setValue] = useState('file')
    const [fileId, setFileId] = useState('')
    const { t } = useTranslation('knowledge')

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
                    <TabsTrigger value="file" className="rounded-xl">
                        {t('fileManagement')}
                    </TabsTrigger>
                    <TabsTrigger value="chunk">
                        {t('chunkManagement')}
                    </TabsTrigger>
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
