
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { AppType } from '@/types/app';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../../components/bs-ui/button';
import { Input, Textarea } from '../../../components/bs-ui/input';
import { createTempApi } from '../../../controllers/API';
import { captureAndAlertRequestErrorHoc } from '../../../controllers/request';
import { FlowType } from '../../../types/flow';

export default function CreateTemp({ flow, open, type, setOpen, onCreated }) {
    const { t } = useTranslation();

    const [data, setData] = useState({
        name: '',
        description: ''
    });

    useEffect(() => {
        open && setData({
            name: flow.name,
            description: flow.description || ''
        });
    }, [open]);

    const { message } = useToast();
    const handleSubmit = () => {
        const nameMap = {
            [AppType.FLOW]: t('build.workFlow'),
            [AppType.SKILL]: t('build.skillName'),
            [AppType.ASSISTANT]: t('build.assistant')
        };
        const labelName = nameMap[type];
        const errorlist = [];

        const { name, description } = data;
        if (!name) errorlist.push(t('build.pleaseFillIn', { labelName }));
        if (name.length > 30) errorlist.push(t('build.nameTooLong', { labelName }));
        if (!description && type === AppType.ASSISTANT) errorlist.push(t('build.addDescription', { labelName }));
        if (description.length > 200) errorlist.push(t('build.descriptionTooLong', { labelName }));
        if (errorlist.length) message({
            variant: 'error',
            description: errorlist
        });

        captureAndAlertRequestErrorHoc(
            createTempApi({ ...data, flow_id: flow.id }, type)
                .then((res) => {
                    setOpen(false);
                    message({
                        variant: 'success',
                        description: t('build.templateCreatedSuccessfully')
                    });
                    onCreated?.();
                })
        );
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className='sm:max-w-[625px]'>
                <DialogHeader>
                    <DialogTitle>{t('skills.createTemplate')}</DialogTitle>
                </DialogHeader>
                <div className='flex flex-col gap-4 py-2'>
                    <div className=''>
                        <label htmlFor='name' className='bisheng-label'>
                            {type === AppType.SKILL ? t('skills.skillName') : type === AppType.ASSISTANT ? t('build.assistantName') : t('build.workFlowName')}
                        </label>
                        <Input
                            name='name'
                            className='mt-2'
                            value={data.name}
                            onChange={(e) => setData({ ...data, name: e.target.value })}
                        />
                    </div>
                    <div className=''>
                        <label htmlFor='roleAndTasks' className='bisheng-label'>
                            {t('skills.description')}
                        </label>
                        <Textarea
                            id='name'
                            value={data.description}
                            onChange={(e) => setData({ ...data, description: e.target.value })}
                            className='col-span-2'
                        />
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant='outline' className='px-11' type='button' onClick={() => setOpen(false)}>
                            {t('build.cancel')}
                        </Button>
                    </DialogClose>
                    <Button type='submit' className='px-11' onClick={handleSubmit}> {t('build.create')} </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}