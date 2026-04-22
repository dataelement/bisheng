
import KnowledgeUploadComponent from "@/components/bs-comp/knowledgeUploadComponent";
import { Button } from "@/components/bs-ui/button";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";

export default function FileUploadStep1({ hidden, onNext, onSave, initialFiles }) {
    const { t } = useTranslation('knowledge')
    const { id: kid } = useParams()
    const { appConfig } = useContext(locationContext)
    const tableExtensions = ['xlsx', 'xls', 'csv', 'et']

    const [fileCount, setFileCount] = useState(0)
    const [finish, setFinish] = useState(false)
    const filesRef = useRef<any>([])
    const failFilesRef = useRef<any>([])

    const handleFileChange = (files, failFiles) => {

        filesRef.current = files.map(file => ({
            ...file,
            suffix: file.fileName.split('.').pop().toLowerCase() || 'txt',
            fileType: tableExtensions.includes(file.fileName.split('.').pop().toLowerCase()) ? 'table' : 'file',
            fileId: 0
        }))
        failFilesRef.current = failFiles

        setFinish(!failFiles.length)
    }

    const [loading, setLoading] = useState(false)
    const handleSave = async () => {
        const params = {
            knowledge_id: kid,
            file_list: filesRef.current.map(file => ({
                file_path: file.file_path,
                excel_rule: file.fileType === 'file' ? {} : {
                    "append_header": true,
                    "header_end_row": 1,
                    "header_start_row": 1,
                    "slice_length": 10
                }
            })),
            separator: ["\n\n", "\n"],
            separator_rule: ["after", "after"],
            chunk_size: 1000,
            chunk_overlap: 100,
            retain_images: true,
            enable_formula: true,
            force_ocr: true,
            fileter_page_header_footer: true
        }

        setLoading(true)
        await onSave(params)
        setLoading(false)
    }
    useEffect(() => {
        if (initialFiles.length > 0) {
            handleFileChange(initialFiles, []);
            setFileCount(initialFiles.length);

        }
    }, [initialFiles]);
    return <div className={`relative mx-auto flex h-full w-full max-w-[1120px] flex-col pb-28 pt-6 ${hidden ? 'hidden' : ''}`}>
        <KnowledgeUploadComponent
            size={appConfig.uploadFileMaxSize}
            progressClassName='max-h-[420px]'
            knowledgeId={kid}
            onSelectFile={(count) => {
                setFileCount(count)
                setFinish(false)
            }}
            onFileChange={handleFileChange}
            initialFiles={initialFiles}
        />
        <div className="fixed bottom-0 left-0 right-0 z-30 flex justify-center gap-4 border-t border-[#e4e8ee] bg-white px-4 py-4 sm:left-[184px]">
            <Button disabled={loading || !finish} variant="outline" onClick={handleSave}>{t("uploadDirectly")}</Button>
            <Button disabled={loading || !finish} onClick={() => {
                onNext(filesRef.current)
            }} >
                {fileCount ? <span>{t('totalFiles', { count: fileCount })}</span> : null}&nbsp;{t('nextStep')}</Button>
        </div>
    </div>

};
