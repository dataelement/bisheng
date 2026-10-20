import { Tabs } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import SystemLog from "./systemLog";
import AppUseLog from "./useAppLog";

export default function index() {
    const { t } = useTranslation()

    return <div id="model-scroll" className="w-full h-full px-2 pt-4">
        <Tabs defaultActiveKey="app" className="w-full mb-10" items={[
            { key: 'app', label: t('log.appUsage'), children: <div className="pt-2"><AppUseLog /></div> },
            { key: 'system', label: t('log.systemOperations'), children: <div className="pt-2"><SystemLog /></div> },
        ]} />
    </div>
};
