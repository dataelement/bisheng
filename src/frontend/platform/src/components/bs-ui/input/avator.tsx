import { Camera, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useToast } from "../toast/use-toast";
import { cname } from "../utils";

// 头像
export default function Avator({
    size = 5 * 1024 * 1024,
    accept = "image/jpeg,image/png",
    value,
    close = false,
    className,
    onChange,
    children
}) {
    const { message } = useToast();
    const { t } = useTranslation()
    const defaultButtonName = t('build.uploadAvator');

    const handleFileChange = (event) => {
        const file = event.target.files[0];
        if (file) {
            const isValidSize = file.size <= size;
            const isValidType = accept.split(',').some(type => file.type === type);

            const errormgs = []
            if (!isValidSize) errormgs.push(`${t('build.fileSizeLimit')} ${size / 1024 / 1024}MB`)
            if (!isValidType) errormgs.push(`${t('build.fileTypeLimit')} ${accept}`)

            errormgs.length ? message({
                variant: 'error',
                description: errormgs
            }) : onChange(file)
        }
    };

    return <div className={cname("flex w-full rounded-md gap-4", className)}>
        <div className="relative group">
            {
                value ? <img src={value} className="max-w-24 max-h-24 min-w-8 min-h-8 rounded-md object-cover border" alt="" /> : children
            }
            <div className="absolute left-0 top-0 w-full h-full opacity-0 group-hover:opacity-100 transition-opacity duration-300 bg-black/50 flex items-center justify-center rounded-md">
                <input
                    className="absolute top-0 left-0 inset-0 w-full h-full opacity-0 cursor-pointer"
                    type="file"
                    accept={accept}
                    onChange={handleFileChange}
                />
                <Camera className="text-gray-50 w-6 h-6" />
                {close && value && <div className="absolute -top-3 -right-3 bg-gray-50 rounded-full p-1 cursor-pointer border border-gray-300" onClick={() => onChange(null)}><X size={14} /></div>}
            </div>
        </div>
        {/* <Button variant="outline" className="relative">
            {buttonName || defaultButtonName}
            <input
                className=" absolute top-0 left-0 inset-0 w-full h-full opacity-0 cursor-pointer"
                type="file"
                accept={accept}
                onChange={handleFileChange}
            />
        </Button> */}
    </div>
};
