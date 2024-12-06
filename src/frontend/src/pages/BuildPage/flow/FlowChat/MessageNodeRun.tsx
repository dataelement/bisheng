import { LoadIcon, ToastIcon } from "@/components/bs-icons";

export default function MessageNodeRun({ data }) {

    return <div className="py-1">
        <div className="rounded-sm border">
            <div className="flex justify-between items-center px-4 py-2 cursor-pointer">
                <div className="flex items-center font-bold gap-2 text-sm">
                    {
                        <LoadIcon className="text-primary duration-300" />
                    }
                    <span>正在运行 {data.message.name} 节点</span>
                </div>
            </div>
        </div>
    </div>
};
