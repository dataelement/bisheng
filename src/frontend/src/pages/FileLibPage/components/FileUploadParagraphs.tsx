import SelectSearch from "@/components/bs-ui/select/select";
import { InfoCircledIcon } from "@radix-ui/react-icons";
import { forwardRef, useImperativeHandle, useRef, useState } from "react"
import { ParagraphsItem } from "./Paragraphs";
import ParagraphEdit from "./ParagraphEdit";
import { Dialog, DialogContent } from "@/components/bs-ui/dialog";

const FileUploadParagraphs = forwardRef(function ({ change, onChange }: any, ref) {
    const dataRef = useRef<any>(null)
    const [loading, setLoading] = useState(false)
    const [paragraph, setParagraph] = useState<any>({
        id: '',
        show: false
    })

    useImperativeHandle(ref, () => ({
        load(data) {
            setLoading(true)
            dataRef.current = data
        }
    }))

    const handleSelectSearch = (value: any) => {
        console.log('value :>> ', value);
        handleReload()
    }

    const handleReload = () => {
        setLoading(true)
        onChange(false)
    }

    if (loading) return (
        <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>
    )

    return <div className="h-full overflow-y-auto p-2">
        <div className="flex gap-2">
            <SelectSearch value={''} options={[{ label: '1', value: ' 1' }]}
                selectPlaceholder=''
                inputPlaceholder=''
                selectClass="w-64"
                onChange={handleSelectSearch}
                onValueChange={handleSelectSearch}>
            </SelectSearch>
            <div className={`${change ? '' : 'hidden'} flex items-center`}>
                <InfoCircledIcon className='mr-1' />
                <span>检测到策略调整，</span>
                <span className="text-primary cursor-pointer" onClick={handleReload}>重新生成预览</span>
            </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
            {
                [1, 2, 3, 4, 5, 6, 7, 7].map(item => (
                    <ParagraphsItem key={item} data={{}} onEdit={(id) => setParagraph({ id, show: true })} />
                ))
            }
        </div>
        <Dialog open={paragraph.show} onOpenChange={(show) => setParagraph({ ...paragraph, show })}>
            <DialogContent className='size-full max-w-full sm:rounded-none p-0 border-none'>
                <ParagraphEdit id={paragraph.id} onClose={() => setParagraph({ ...paragraph, show: false })} />
            </DialogContent>
        </Dialog>
    </div>
});

export default FileUploadParagraphs