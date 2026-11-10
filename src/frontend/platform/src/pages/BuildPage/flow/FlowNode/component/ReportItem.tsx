// @ts-strict-ignore
import { Button, Input } from '@bisheng/ui';


import { Dialog,DialogContent,DialogTrigger } from '@/components/bs-ui/dialog';

import { Label } from '@/components/bs-ui/label';
import { useEffect,useState } from 'react';
import { useTranslation } from 'react-i18next';
import ReportWordEdit from './ReportWordEdit';

export default function ReportItem({ nodeId, data, onChange, onValidate, i18nPrefix }) {
    const { t } = useTranslation('flow');
    const [value, setValue] = useState({
        name: data.value.file_name || '',
        key: data.value.version_key || ''
    });

    const handleChange = (key) => {
        setValue({ ...value, key });
        onChange({
            file_name: value.name,
            version_key: key
        });
    };

    const [error, setError] = useState(false);
    useEffect(() => {
        onValidate(() => {
            if (String(data.value.file_name ?? "").length > 100) {
                setError(true);
                return t("bs:sharedUi.maximum", { max: 100 });
            }
            if (data.required && !data.value.file_name) {
                setError(true);
                return t('cannotBeEmpty', { label: t(`${i18nPrefix}label`) });
            }
            setError(false);
            return false;
        });

        return () => onValidate(() => { });
    }, [data.value, data.required]);

    return (
        <div className='node-item mb-4 nodrag' data-key={data.key}>
            <Label className='bisheng-label'>
                {data.required && <span className='text-red-500'>*</span>}
                {t(`${i18nPrefix}label`)}
            </Label>
            <Input value={value.name} placeholder={t(`${i18nPrefix}placeholder`)} maxLength={100} showCount onChange={(e) => {
                    setValue({ ...value, name: e.target.value });
                    onChange({
                        file_name: e.target.value,
                        version_key: value.key
                    });
                }} className={`mt-2 ${error && 'border-red-500'}`}></Input>

            <Dialog>
                <DialogTrigger asChild>
                    <Button id={value.key} variant="outlined" className='border-primary text-primary mt-2 h-8' color="default">
                        {t('editReportTemplate')}
                    </Button>
                </DialogTrigger>
                <DialogContent close={false} className='size-full lg:max-w-full pt-12' onKeyDown={(e) => {
                    e.stopPropagation();
                }}>
                    <ReportWordEdit nodeId={nodeId} versionKey={value.key} onChange={handleChange} />
                </DialogContent>
            </Dialog>
        </div>
    );
}