
import KnowledgeUploadComponent from "@/components/bs-comp/knowledgeUploadComponent";
import { Button } from "@/components/bs-ui/button";
import { locationContext } from "@/contexts/locationContext";
import { useContext, useRef, useState } from "react";

export default function FileUploadStep1({ hidden, onNext, onSave }) {
    // const { t } = useTranslation('knowledge')
    const { appConfig } = useContext(locationContext)

    const [fileCount, setFileCount] = useState(0)
    const [finish, setFinish] = useState(false)
    const filesRef = useRef<any>([])
    const failFilesRef = useRef<any>([])

    const handleFileChange = (files, failFiles) => {
        filesRef.current = files.map(file => ({
            ...file,
            fileType: ['xlsx', 'xls', 'csv'].includes(file.fileName.split('.').pop().toLowerCase()) ? 'table' : 'file'
        }))
        // TODO 提示 failFiles
        failFilesRef.current = failFiles

        setFinish(true)
    }

    return <div className={`max-w-[1200px] mx-auto flex flex-col px-10 pt-4 ${hidden ? 'hidden' : ''}`}>
        <KnowledgeUploadComponent
            size={appConfig.uploadFileMaxSize}
            progressClassName='h-[calc(100vh-400px)]'
            onSelectFile={(count) => {
                setFileCount(count)
                setFinish(false)
            }}
            onFileChange={handleFileChange}
        />
        <div className="absolute bottom-2 right-0 flex justify-end gap-4">
            <Button disabled={!finish} variant="outline" onClick={() => onSave(filesRef.current)}>直接上传</Button>
            <Button disabled={!finish} onClick={() => onNext(filesRef.current)} >
                {fileCount ? <span>共{fileCount}个文件</span> : null} 下一步</Button>
        </div>
    </div>

};
