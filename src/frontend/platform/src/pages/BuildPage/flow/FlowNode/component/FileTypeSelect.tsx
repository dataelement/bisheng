import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { Select } from "@bisheng/ui";

import { locationContext } from "@/contexts/locationContext";
import {
normalizeFileAccept,
type UploadFileKind,
} from "@/util/fileAcceptUtils";
import { useContext,useEffect,useMemo,useState } from "react";
import { useTranslation } from "react-i18next";

interface FileTypeSelectProps {
    data: {
        label: string;
        value: UploadFileKind[] | 'all' | 'file' | 'image' | string;
    };
    onChange: (value: UploadFileKind[]) => void;
    i18nPrefix?: string;
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

    const selectLabels = useSelectLabels();

    // Short kind name as the label (it lands in the trigger tags); the
    // extension list goes in the one-line description.
    const options = useMemo(() => {
        const base: { label: string; value: UploadFileKind; description: string }[] = [
            {
                label: t('document'),
                description: 'pdf, ofd, txt, md, html, xls, xlsx, doc, docx, ppt, pptx',
                value: 'file',
            },
            {
                label: t('image'),
                description: 'png, jpg, jpeg, bmp',
                value: 'image',
            },
        ];
        if (mediaEnabled) {
            base.push({
                label: t('media'),
                description: 'mp3, wav, m4a, aac, flac, ogg, mp4, mov, avi, mkv, webm',
                value: 'media',
            });
        }
        return base;
    }, [mediaEnabled, t]);

    const handleChange = (values: (string | number)[]) => {
        const next = values.map(String) as UploadFileKind[];
        setKinds(next);
        onChange(next);
    };

    const label = i18nPrefix ? t(`${i18nPrefix}label`) : data.label;

    return (
        <div className='node-item flex gap-4 items-center mb-4'>
            <Label className="bisheng-label min-w-28">
                {label}
            </Label>
            <Select
                {...selectLabels}
                multiple
                options={options}
                value={kinds}
                onChange={handleChange}
                placeholder={t('noFileTypesSelected')}
                aria-label={label}
                className="nodrag min-w-0 flex-1"
            />
        </div>
    );
}
