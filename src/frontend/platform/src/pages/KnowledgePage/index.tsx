// @ts-strict-ignore
import { Tabs } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

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
                { key: 'file', label: t('lib.fileData'), icon: <Outlined.Books aria-hidden="true" />, children: <KnowledgeFile toolbarTarget={toolbarTarget} /> },
                { key: 'qa', label: t('lib.qaData'), icon: <Outlined.BookOpenText aria-hidden="true" />, children: <KnowledgeQa toolbarTarget={toolbarTarget} /> },
            ]} />
        </div>
    );
}
