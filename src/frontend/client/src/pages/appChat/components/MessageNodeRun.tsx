

import { Loader2 } from "lucide-react";
import useLocalize from "~/hooks/useLocalize";

export default function MessageNodeRun({ data }) {

    const t = useLocalize()

    return <div className="py-1">
        <div className="rounded-sm">
            <div className="flex justify-between items-center px-4 py-2 cursor-pointer">
                <div className="flex items-center font-bold gap-2 text-sm">
                    {
                        <Loader2 className="text-primary animate-spin duration-300" />
                    }
                    <span>{t('com_node_run_running')} {data.message.name}</span>
                </div>
            </div>
        </div>
    </div>
};
