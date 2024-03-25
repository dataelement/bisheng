import { Button } from "@/components/bs-ui/button";
import { DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Textarea } from "@/components/ui/textarea";

export default function AutoPromptDialog({ onOpenChange }) {

    return <DialogContent className="sm:max-w-[825px]">
        <DialogHeader>
            <DialogTitle>助手画像优化</DialogTitle>
        </DialogHeader>
        <div className="">
            <div>
                <div></div>
                <Textarea></Textarea>
            </div>
            <div>
                <div></div>
                <div>
                    div.cart
                </div>
            </div>
        </div>
        <DialogFooter>
            <DialogClose>
                <Button variant="outline" className="px-10" type="button">取消</Button>
            </DialogClose>
            <Button type="submit" className="px-10">全部使用</Button>
        </DialogFooter>
    </DialogContent>
};
