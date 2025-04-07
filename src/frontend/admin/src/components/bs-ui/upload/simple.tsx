import { UploadIcon } from "@/components/bs-icons";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { useToast } from "../toast/use-toast";
import { cname } from "../utils";
import axios from "@/controllers/request";

export default function SimpleUpload({ filekey, uploadUrl, accept, className = '', onUpload, onProgress, onError, onSuccess }) {
    const { t } = useTranslation();
    const { toast } = useToast()

    const onDrop = async (acceptedFiles) => {
        const sizeLimit = 50 * 1024 * 1024;
        const errorFile = [];
        const files = []
        acceptedFiles.forEach(file => {
            file.size < sizeLimit ?
                files.push(file) :
                errorFile.push(file.name);
        });
        errorFile.length && toast({
            title: t('prompt'),
            description: errorFile.map(str => `${t('code.file')}: ${str} ${t('code.sizeExceedsLimit')}`),
        });
        if (!files.length) return

        const formData = new FormData();
        formData.append(filekey, files[0]);

        const res = await axios.post(uploadUrl, formData);
        onSuccess(files[0].name, res.file_path)
    }

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        accept: {
            'application/*': accept.map(str => `.${str}`)
        },
        multiple: false,
        useFsAccessApi: false,
        onDrop
    });


    return <div {...getRootProps()} className={cname('group h-[100px] border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary', className)}>
        <input {...getInputProps()} />
        <UploadIcon className="group-hover:text-primary" />
        {isDragActive ? <p className="text-gray-400 text-sm">{t('code.dropFileHere')}</p> : <p className="text-gray-400 text-sm">{t('code.clickOrDragHere')}</p>}
    </div>
};
