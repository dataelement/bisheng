
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogTrigger } from '@/components/bs-ui/dialog';
import { Input } from '@/components/bs-ui/input';
import { Label } from '@/components/bs-ui/label';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ReportWordEdit from './ReportWordEdit';

export default function ReportItem({ nodeId, data, onChange, onValidate }) {
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
        data.required && onValidate(() => {
            if (!data.value.file_name) {
                setError(true);
                return t('cannotBeEmpty', { label: data.label });
            }
            setError(false);
            return false;
        });

        return () => onValidate(() => { });
    }, [data.value]);

    return (
        <div className='node-item mb-4 nodrag' data-key={data.key}>
            <Label className='bisheng-label'>
                {data.required && <span className='text-red-500'>*</span>}
                {data.label}
            </Label>
            <Input
                value={value.name}
                className={`mt-2 ${error && 'border-red-500'}`}
                placeholder={data.placeholder}
                maxLength={100}
                showCount
                onChange={(e) => {
                    setValue({ ...value, name: e.target.value });
                    onChange({
                        file_name: e.target.value,
                        version_key: value.key
                    });
                }}
            ></Input>

            <Dialog>
                <DialogTrigger asChild>
                    <Button id={value.key} variant='outline' className='border-primary text-primary mt-2 h-8'>
                        {t('editReportTemplate')}
                    </Button>
                </DialogTrigger>
                <DialogContent close={false} className='size-full lg:max-w-full pt-12'>
                    <ReportWordEdit nodeId={nodeId} versionKey={value.key} onChange={handleChange} />
                </DialogContent>
            </Dialog>
        </div>
    );
}