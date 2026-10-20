import { Button } from '@bisheng/ui';

import { Alert,AlertDescription,AlertTitle } from "@/components/bs-ui/alert";

import { Popover,PopoverContent,PopoverTrigger } from "@/components/bs-ui/popover";
import { darkContext } from "@/contexts/darkContext";
import { Outlined } from "bisheng-icons";

import { useContext,useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "./flowStore";

export default function Notification() {
    const { t } = useTranslation();
    const { dark } = useContext(darkContext);
    const [open, setOpen] = useState(false);

    const notifications = useFlowStore((state) => state.notifications);
    const clearNotifications = useFlowStore((state) => state.clearNotifications);

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button size="medium" variant="outlined" className={`${!dark && 'bg-[#fff]'} size-8 relative`} color="default" iconOnly>
                    <Outlined.Bell size={16} />
                    {notifications.length > 0 && <div className="absolute top-1 right-1 rounded-full bg-status-red size-1.5"></div>}
                </Button>
            </PopoverTrigger>
            <PopoverContent className="p-2 cursor-pointer w-[400px] h-[500px] pb-10">
                <div className="text-md flex flex-row justify-between pl-3 font-medium text-foreground">
                    {t("flow.notification")}
                    <div className="flex gap-3 pr-3">
                        <button
                            className="text-foreground hover:text-status-red"
                            onClick={clearNotifications}
                        >
                            <Outlined.Delete className="h-[1.1rem] w-[1.1rem]" />
                        </button>
                        <button
                            className="text-foreground hover:text-status-red"
                            onClick={() => setOpen(false)}
                        >
                            <Outlined.Close className="h-5 w-5" />
                        </button>
                    </div>
                </div>
                <div className="text-high-foreground mt-3 flex h-full w-full flex-col overflow-y-scroll scrollbar-hide">
                    {notifications.length > 0 ? (
                        notifications.map((notification, index) => (
                            <Alert data-type={notification.type} // set attr
                                className="p-4 rounded-md mb-2
                                border
                                data-[type=success]:border-[#10b981]
                                data-[type=error]:border-[#D8341E]
                                data-[type=warning]:border-[#f59e0b]
                                data-[type=info]:border-[#3b82f6]
                                data-[type=success]:bg-[#d1fae5]
                                data-[type=error]:bg-[#fee2e2]
                                data-[type=warning]:bg-[#fef9c3]
                                data-[type=info]:bg-[#dbeafe]"
                                key={index}
                            >
                                {notification.type === "error" ? <Outlined.CloseCircle size={20} className="text-danger" /> : notification.type === "success" ? <Outlined.CheckCircle size={20} className="text-success" /> : notification.type === "warning" ? <Outlined.Attention size={20} className="text-warning" /> : <Outlined.Info size={20} className="text-primary" />}
                                <AlertTitle>{notification.title}</AlertTitle>
                                <AlertDescription className="break-words whitespace-pre-wrap overflow-wrap-anywhere">
                                    {notification.description}
                                </AlertDescription>
                            </Alert>
                        ))
                    ) : (
                        <div className="flex h-full w-full items-center justify-center pb-16 text-ring">
                            {t("flow.noNewNotifications")}
                        </div>
                    )}
                </div>
            </PopoverContent>
        </Popover>
    );
}
