import { Tabs, TabsContent } from "@/components/bs-ui/tabs";
import { useState } from "react";
import Files from "./components/Files";
import Header from "./components/Header";
import Paragraphs from "./components/Paragraphs";

export default function FilesPage() {
    const [value, setValue] = useState('file')
    const [fileId, setFileId] = useState('')
    const [fileTitle, setFileTitle] = useState(true);

    const onPreview = (id: string) => {
        setFileId(id)
        setValue('chunk')
        setFileTitle(false)
    }
    const handleBackFromChunk = () => {
        if (value === 'chunk') {
            setValue('file');
            setFileId('');
            setFileTitle(true)
        }
    };
    return <div className="size-full px-2 relative bg-background-login">
        {/* tab */}
        <Tabs value={value} onValueChange={(v) => {
            setValue(v);
            setFileId('');
            if (v === 'file') {
                setFileTitle(true);
            } else {
                setFileTitle(false);
            }
        }}>
            <TabsContent value="file" className="mt-0">
                <div className="flex justify-between w-1/2 pt-4">
                    <Header fileTitle={fileTitle} showBackButton={true} />
                </div>
                <Files onPreview={onPreview} />
            </TabsContent>
            <TabsContent value="chunk" className="mt-0">
                <Paragraphs fileId={fileId} onBack={handleBackFromChunk} />
            </TabsContent>
        </Tabs>
    </div>
};
