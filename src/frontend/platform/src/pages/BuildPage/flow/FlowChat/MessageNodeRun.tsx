import { Outlined } from "bisheng-icons";


export default function MessageNodeRun({ data }) {
    // const { t } = useTranslation('flow')

    return <div className="py-1">
        <div className="rounded-sm border">
            <div className="flex justify-between items-center px-4 py-2 cursor-pointer">
                <div className="flex items-center font-bold gap-2 text-sm">
                    {
                        <Outlined.Loading size={16} className="animate-spin text-primary duration-300" />
                    }
                    <span>{data.message.name}</span>
                </div>
            </div>
        </div>
    </div>
};
