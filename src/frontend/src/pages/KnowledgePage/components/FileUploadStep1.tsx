
import { Button } from "@/components/bs-ui/button";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import Upload from "@/components/bs-ui/upload";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function FileUploadStep1({ hidden, onNext, onChange }) {
    const { t } = useTranslation('knowledge')
    const { appConfig } = useContext(locationContext)
    const uploadRef = useRef<any>(null)
    const { message } = useToast()

    const [fileCount, setFileCount] = useState(0)
    // useEffect(() => {
    //     onChange()
    // }, [fileCount])

    const handleSaveFiles = () => {
        const [fileCount, files, failFiles] = uploadRef.current?.getUploadResult()
        if (!files.length) return message({ variant: 'error', description: t('code.selectFileToUpload', { ns: 'bs' }) })
        onNext({ fileCount, files, failFiles })
    }

    return <div className={`flex flex-col ${hidden ? 'hidden' : ''}`}>
        <div className="flex items-center gap-2 my-6 px-12 text-sm font-bold max-w-96">
            <span className="text-primary">{t('step1UploadFile')}</span>
            <div className="h-[1px] flex-grow bg-gray-300"></div>
            <span>{t('step2DocProcessing')}</span>
        </div>
        <Upload
            ref={uploadRef}
            url='/api/v1/knowledge/upload'
            accept={appConfig.libAccepts}
            progressClassName='max-h-[374px]'
            onFileCountChange={(count, all) => {
                console.log('count all :>> ', count, all);
                setFileCount(count === all ? count : 0)
            }
            }
            onBeforeUpload={() => setFileCount(0)}
        />
        <div className="flex justify-end">
            <Button className="px-10 mt-4" disabled={!fileCount} onClick={handleSaveFiles}>
                {fileCount ? <span>{t('totalFiles', { count: fileCount })}<span className="mx-1">|</span></span> : null}
                {t('nextStep')}
            </Button>
        </div>
    </div>

};
