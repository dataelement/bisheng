import { Button } from '@bisheng/ui';

import { Dialog, DialogContent } from "@/components/bs-ui/dialog";
import { handleUiRequest } from "@/controllers/request";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function Preview({ onBeforView }) {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const benchUrl = location.origin + "/workspace/";

    const handleClick = async () => {
        const res = await onBeforView();
        if (res) {
            setOpen(true);
        }
    };

    return (
        <Dialog onOpenChange={setOpen} open={open}>
            <Button variant="outlined" onClick={handleUiRequest(handleClick)} color="default">
                {t("chatConfig.savePreview")}
            </Button>
            <DialogContent className="max-w-[90vw] h-[90vh]">
                <div className="grid gap-4 py-4">{open && <iframe src={benchUrl} className="size-full"></iframe>}</div>
                {/* <DialogFooter>
                <Button type="submit">Save changes</Button>
            </DialogFooter> */}
            </DialogContent>
        </Dialog>
    );
}
