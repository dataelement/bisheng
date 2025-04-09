import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/bs-ui/tabs";

import { useTranslation } from "react-i18next";
import KnowledgeFile from "./KnowledgeFile";
import KnowledgeQa from "./KnowledgeQa";


export default function index() {

    const { t } = useTranslation();

    const defaultValue = (() => {
        const page = window.LibPage;
        return page ? page.type : 'file'
    })();

    return (
        <div className="w-full h-full px-2 pt-4 relative">
            <Tabs defaultValue={defaultValue} className="w-full mb-[40px]">
                <TabsList className="">
                    <TabsTrigger value="file">{t('lib.fileData')}</TabsTrigger>
                    <TabsTrigger value="qa" className="roundedrounded-xl">{t('lib.qaData')}</TabsTrigger>
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