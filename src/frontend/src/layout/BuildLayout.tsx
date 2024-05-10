import { TabIcon } from "@/components/bs-icons/tab";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

export default function BuildLayout(params) {

    const { t } = useTranslation()

    return <div className="bg-[#F4F5F8]">
        <div className="build-tab flex justify-center h-[60px] items-center border-b relative top-[-60px]">
            <div className="px-4">
                <NavLink to={'assist'} className="group flex gap-2 items-center px-8 py-2 rounded-md">
                    <TabIcon className="group-hover:text-primary"></TabIcon>
                    <span className="text-sm font-bold">{t('build.assistant')}</span>
                </NavLink>
            </div>
            <div className="px-4">
                <NavLink to={'skills'} className="group flex gap-2 items-center px-8 py-2 rounded-md">
                    <TabIcon className="group-hover:text-primary"></TabIcon>
                    <span className="text-sm font-bold">{t('build.skill')}</span>
                </NavLink>
            </div>
            <div className="px-4">
                <NavLink to={'tools'} className="group flex gap-2 items-center px-8 py-2 rounded-md">
                    <TabIcon className="group-hover:text-primary"></TabIcon>
                    <span className="text-sm font-bold">{t('build.tools')}</span>
                </NavLink>
            </div>
        </div>
        <div className="" style={{ height: 'calc(100vh - 125px)' }}>
            <Outlet />
        </div>
    </div>
};
