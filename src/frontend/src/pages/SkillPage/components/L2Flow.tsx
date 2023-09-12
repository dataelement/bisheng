import { Button } from "../../../components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Textarea } from "../../../components/ui/textarea";

export default function L2Flow({ open, setOpen }) {

    return <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger></DialogTrigger>
        <DialogContent className="">
            <DialogHeader>
                <DialogTitle>应用技能</DialogTitle>
                <DialogDescription>这里可以编辑技能，高级技能可以。。。</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="name" className="text-right">技能名称</Label>
                    <Input id="name" value="Pedro Duarte" className="col-span-3" />
                </div>
                <div className="grid grid-cols-4 items-center gap-4">
                    <Label htmlFor="username" className="text-right">描述</Label>
                    <Textarea id="name" value="Pedro Duarte" className="col-span-3" />
                </div>
            </div>
            <DialogFooter>
                <Button type="submit" className="h-8" onClick={() => { }}>创建</Button>
            </DialogFooter>
        </DialogContent>
    </Dialog>
};
