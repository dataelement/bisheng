// @ts-strict-ignore
import { Tabs } from "@bisheng/ui";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import KnowledgeFile from "./KnowledgeFile";
import KnowledgeQa from "./KnowledgeQa";


export default function KnowledgePage() {

    const { t } = useTranslation();
    const [toolbarTarget, setToolbarTarget] = useState<HTMLDivElement | null>(null);

    const defaultValue = (() => {
        const page = window.LibPage;
        return page ? page.type : 'file'
    })();

    return (
        <div className="w-full h-full px-2 pt-4 relative">
            <Tabs defaultActiveKey={defaultValue}
                extra={<div ref={setToolbarTarget} />}
                className="w-full mb-10 [&>div:first-child]:mx-2 [&>div:first-child]:mb-2" items={[
                { key: 'file', label: t('lib.fileData'), children: <KnowledgeFile toolbarTarget={toolbarTarget} /> },
                { key: 'qa', label: t('lib.qaData'), children: <KnowledgeQa toolbarTarget={toolbarTarget} /> },
            ]} />
        </div>
    );
}
