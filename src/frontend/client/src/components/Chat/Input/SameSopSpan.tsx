import { ArrowRight, CircleX } from "lucide-react"
import { atom, useRecoilState } from "recoil"
import { Button } from "~/components/ui"
import { useLocalize } from "~/hooks";

export default function SameSopSpan() {
    const [sameSopLabel, setSameSopLabel] = useRecoilState(sameSopLabelState)
    const t = useLocalize();

    const handleClose = () => {
        setSameSopLabel(null)
    }

    const handleCardClick = () => {
        window.open(`${__APP_ENV__.BASE_URL}/linsight/case/${sameSopLabel.id}`)
    }

    if (!sameSopLabel) return null

    return <div className="p-2 px-6">
        <div className="flex items-center justify-between border-b bg-background rounded-sm">
            <div className="flex items-center gap-3">
                <Button variant="ghost" size="sm" className="h-8 text-xs rounded-sm bg-primary/20 text-blue-600 hover:text-blue-700">
                    <ArrowRight className="h-3 w-3" />
                    {t('com_make_samestyle')}
                </Button>
            </div>

            <div className="flex-1 pl-2" onClick={handleCardClick}>
                <p className="text-sm text-foreground underline truncate max-w-80 sm:max-w-[555px]">{sameSopLabel.name}</p>
            </div>

            <div className="flex items-center">
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleClose}
                    className="h-8 text-muted-foreground hover:text-foreground"
                >
                    <CircleX className="h-4 w-4" />
                </Button>
            </div>
        </div>
    </div>
};

export type SameSopLabel = {
    id: string
    name: string
} | null

export const sameSopLabelState = atom<SameSopLabel>({
    key: "sameSopLabelState",
    default: null,
})