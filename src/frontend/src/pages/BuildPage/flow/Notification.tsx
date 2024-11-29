import { ToastIcon } from "@/components/bs-icons";
import { Alert, AlertDescription, AlertTitle } from "@/components/bs-ui/alert";
import { Button } from "@/components/bs-ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { Bell, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import useFlowStore from "./flowStore";

export default function Notification() {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);

    const notifications = useFlowStore((state) => state.notifications);
    const clearNotifications = useFlowStore((state) => state.clearNotifications);

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button size="icon" variant="outline" className="bg-[#fff] h-8">
                    <Bell size={16} />
                </Button>
            </PopoverTrigger>
            <PopoverContent className="p-2 cursor-pointer w-[400px] h-[500px]">
                <div className="text-md flex flex-row justify-between pl-3 font-medium text-foreground">
                    {t("flow.notification")}
                    <div className="flex gap-3 pr-3">
                        <button
                            className="text-foreground hover:text-status-red"
                            onClick={clearNotifications}
                        >
                            <Trash2 className="h-[1.1rem] w-[1.1rem]" />
                        </button>
                        <button
                            className="text-foreground hover:text-status-red"
                            onClick={() => setOpen(false)}
                        >
                            <X className="h-5 w-5" />
                        </button>
                    </div>
                </div>
                <div className="text-high-foreground mt-3 flex h-full w-full flex-col overflow-y-scroll scrollbar-hide">
                    {notifications.length > 0 ? (
                        notifications.map((notification, index) => (
                            <Alert data-type={notification.type} // 设置数据属性
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
                                <ToastIcon type={notification.type} />
                                <AlertTitle>{notification.title}</AlertTitle>
                                <AlertDescription>
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
