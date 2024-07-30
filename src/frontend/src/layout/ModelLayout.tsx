import { TabIcon } from "@/components/bs-icons/tab";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

export default function ModelLayout(params) {

    const { t } = useTranslation()

    return <div className="">
        <div className="build-tab flex justify-center h-[65px] items-center border-b relative top-[-65px] bg-background-main z-[100]">
            <div className="px-4">
                <NavLink to={'management'} className="group flex gap-2 items-center px-8 py-2 rounded-md navlink">
                    <TabIcon className="text-muted-foreground group-hover:text-primary dark:group-hover:text-[#fff]"></TabIcon>
                    <span className="text-sm font-bold text-muted-foreground group-hover:text-primary dark:group-hover:text-[#fff]">{t('model.modelManagement')}</span>
                </NavLink>
            </div>
            <div className="px-4">
                <NavLink to={'finetune'} className="group flex gap-2 items-center px-8 py-2 rounded-md navlink">
                    <TabIcon className="text-muted-foreground group-hover:text-primary dark:group-hover:text-[#fff]"></TabIcon>
                    <span className="text-sm font-bold text-muted-foreground group-hover:text-primary dark:group-hover:text-[#fff]">{t('model.modelFineTune')}</span>
                </NavLink>
            </div>
        </div>
        <div className="" style={{ height: 'calc(100vh - 130px)' }}>
            <Outlet />
        </div>
    </div>
};
