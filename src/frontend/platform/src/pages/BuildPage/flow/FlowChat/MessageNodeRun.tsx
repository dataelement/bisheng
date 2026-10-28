import { LoadIcon } from "@/components/bs-icons";

export default function MessageNodeRun({ data }) {
    // const { t } = useTranslation('flow')

    return <div className="py-1">
        <div className="rounded-sm border">
            <div className="px-4 py-2">
                <div className="flex items-center font-bold gap-2 text-sm">
                    <LoadIcon className="text-primary duration-300" />
                    <span>{data.message.name}</span>
                </div>
                {typeof data.message?.reason === "string" && data.message.reason.trim()
                    ? <div className="mt-1 text-sm font-normal whitespace-pre-wrap">{data.message.reason}</div>
                    : null}
            </div>
        </div>
    </div>
};
