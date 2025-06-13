import { LoadIcon } from "@/components/bs-icons";
import { useTranslation } from "react-i18next";

export default function MessageNodeRun({ data }) {
    const { t } = useTranslation('flow')

    return <div className="py-1">
        <div className="rounded-sm border">
            <div className="flex justify-between items-center px-4 py-2 cursor-pointer">
                <div className="flex items-center font-bold gap-2 text-sm">
                    {
                        <LoadIcon className="text-primary duration-300" />
                    }
                    <span title={t('runningNode', { nodeName: data.message.name })}> {data.message.name || '思考中… …'} </span>
                </div>
            </div>
        </div>
    </div>
};
