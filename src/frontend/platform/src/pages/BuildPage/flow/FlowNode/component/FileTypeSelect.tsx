import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select";
import { Check } from "lucide-react";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { locationContext } from "@/contexts/locationContext";
import {
    normalizeFileAccept,
    type UploadFileKind,
} from "@/util/fileAcceptUtils";

interface FileTypeSelectProps {
    data: {
        label: string;
        value: UploadFileKind[] | 'all' | 'file' | 'image' | string;
    };
    onChange: (value: UploadFileKind[]) => void;
    i18nPrefix: string;
}

export default function FileTypeSelect({ data, onChange, i18nPrefix }: FileTypeSelectProps) {
    const { appConfig } = useContext(locationContext);
    const mediaEnabled = !!appConfig.enableMediaUpload;
    const { t } = useTranslation('flow');

    const [kinds, setKinds] = useState<UploadFileKind[]>(() =>
        normalizeFileAccept(data.value, { mediaEnabled }),
    );

    useEffect(() => {
        setKinds(normalizeFileAccept(data.value, { mediaEnabled }));
    }, [data.value, mediaEnabled]);

    const options = useMemo(() => {
        const base: { label: string; value: UploadFileKind }[] = [
            {
                label: t('document') + '（pdf、ofd、txt、md、html、xls、xlsx、doc、docx、ppt、pptx）',
                value: 'file',
            },
            {
                label: t('image') + '（png、jpg、jpeg、bmp）',
                value: 'image',
            },
        ];
        if (mediaEnabled) {
            base.push({
                label: t('media') + '（mp3、wav、m4a、aac、flac、ogg、mp4、mov、avi、mkv、webm）',
                value: 'media',
            });
        }
        return base;
    }, [mediaEnabled, t]);

    const handleToggle = (clicked: UploadFileKind) => {
        let next: UploadFileKind[];
        if (kinds.includes(clicked)) {
            next = kinds.filter((k) => k !== clicked);
        } else {
            next = [...kinds, clicked];
        }
        setKinds(next);
        onChange(next);
    };

    const getDisplayText = () => {
        if (!kinds.length) return t('noFileTypesSelected');
        const labels = kinds.map((k) => {
            if (k === 'file') return t('document');
            if (k === 'image') return t('image');
            return t('media');
        });
        return labels.join('、');
    };

    return (
        <div className='node-item flex gap-4 items-center mb-4'>
            <Label className="bisheng-label min-w-28">
                {i18nPrefix ? t(`${i18nPrefix}label`) : data.label}
            </Label>
            <Select>
                <SelectTrigger>
                    {getDisplayText()}
                </SelectTrigger>
                <SelectContent className="">
                    {options.map((option) => (
                        <div
                            key={option.value}
                            data-focus={kinds.includes(option.value)}
                            className="flex justify-between w-full select-none items-center mb-1 last:mb-0 rounded-sm p-1.5 text-sm outline-none cursor-pointer hover:bg-[#EBF0FF] data-[focus=true]:bg-[#EBF0FF] dark:hover:bg-gray-700 dark:data-[focus=true]:bg-gray-700 data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                            onClick={() => handleToggle(option.value)}
                        >
                            <span className="w-64 overflow-hidden text-ellipsis">
                                {option.label}
                            </span>
                            {kinds.includes(option.value) && <Check className="h-4 w-4" />}
                        </div>
                    ))}
                </SelectContent>
            </Select>
        </div>
    );
}
