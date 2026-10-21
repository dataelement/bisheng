// @ts-strict-ignore
import { Tabs } from "@bisheng/ui";

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
            <Tabs defaultActiveKey={defaultValue} className="w-full mb-10" items={[
                { key: 'file', label: t('lib.fileData'), children: <KnowledgeFile /> },
                { key: 'qa', label: t('lib.qaData'), children: <KnowledgeQa /> },
            ]} />
        </div>
    );
}