import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/bs-ui/dialog";


export default function Preview() {

    return <Dialog>
        <DialogTrigger asChild>
            <Button>效果预览</Button>
        </DialogTrigger>
        <DialogContent className="max-w-[90vw] h-[90vh]">
            <div className="grid gap-4 py-4">
                <iframe src="http://192.168.106.120:3090" className="size-full"></iframe>
            </div>
            {/* <DialogFooter>
                <Button type="submit">Save changes</Button>
            </DialogFooter> */}
        </DialogContent>
    </Dialog>
};
