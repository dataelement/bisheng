import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader } from "@/components/bs-ui/alertDialog";
import { Button } from "@/components/bs-ui/button";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export default function Guide() {
    const [open, setOpen] = useState(false);
    const { t } = useTranslation('knowledge');

    // 检查用户是否选择了“不再提醒”
    useEffect(() => {
        const neverShowAgain = localStorage.getItem("neverShowAgain");
        if (!neverShowAgain) {
            setOpen(true); // 如果用户没有选择“不再提醒”，则显示提醒框
        }
    }, []);

    // 处理【知道了】按钮点击
    const handleCancelClick = () => {
        setOpen(false); // 关闭提醒框
    };

    // 处理【不再提醒】按钮点击
    const handleOkClick = () => {
        localStorage.setItem("neverShowAgain", "true"); // 将用户选择存储在localStorage中
        setOpen(false); // 关闭提醒框
    };

    return (
        <AlertDialog open={open} onOpenChange={setOpen}>
            <AlertDialogContent className="max-w-full size-full bg-black/80 content-center">
                <div className="h-fit w-[1000px] mx-auto bg-background p-4 rounded-md">
                    <AlertDialogHeader className="relative">
                        <AlertDialogDescription className="text-popover-foreground">
                            <p className="text-left mb-4">{t('modifySelection')}</p>
                            <img src="/guide.gif" alt="" />
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter className="gap-x-8 mt-6">
                        <AlertDialogCancel onClick={handleCancelClick} className="px-11">
                            {t('cancel')}
                        </AlertDialogCancel>
                        <Button onClick={handleOkClick} className="px-11">
                            {t('dontRemind')}
                        </Button>
                    </AlertDialogFooter>
                </div>
            </AlertDialogContent>
        </AlertDialog>
    );
}
