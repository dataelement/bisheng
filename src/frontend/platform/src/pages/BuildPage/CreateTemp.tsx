// @ts-strict-ignore
import { Button, Input, Textarea, toast } from '@bisheng/ui';

import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';

import { AppType } from '@/types/app';
import { useContext, useEffect, useRef, useState } from 'react';
import { userContext } from '@/contexts/userContext';
import { canManageAppTemplates } from './templatePermissions';
import { useTranslation } from 'react-i18next';


import { createTempApi } from '@/controllers/API';
import { showApiError } from '@/controllers/request';

export default function CreateTemp({ flow, open, type, setOpen, onCreated }) {
    const { t } = useTranslation();
    const { user } = useContext(userContext);
    const [submitting, setSubmitting] = useState(false);
    const pending = useRef(false);
    const generation = useRef(0);

    const [data, setData] = useState({
        name: '',
        description: ''
    });

    useEffect(() => {
        ++generation.current;
        pending.current = false;
        setSubmitting(false);
        if (open && flow) {
            setData({
                name: flow.name,
                description: flow.description || flow.desc || ''
            });
        }
    }, [open, flow]);


    const handleSubmit = () => {
        if (pending.current || !canManageAppTemplates(user) || !flow) return;
        const nameMap = {
            [AppType.FLOW]: t('build.workFlow'),
            [AppType.ASSISTANT]: t('build.assistant')
        };
        const labelName = nameMap[type];
        const errorlist = [];

        const { name, description } = data;
        if (!name) errorlist.push(t('build.pleaseFillIn', { labelName }));
        if (name.length > 30) errorlist.push(t('build.nameTooLong', { labelName }));
        if (!description && type === AppType.ASSISTANT) errorlist.push(t('build.addDescription', { labelName }));
        if (description.length > 200) errorlist.push(t('build.descriptionTooLong', { labelName }));
        if (errorlist.length) {
            toast.show({ type: 'error', message: errorlist.filter(Boolean).join('\n') });
            return;
        }

        const request = generation.current;
        pending.current = true;
        setSubmitting(true);

        createTempApi({ ...data, flow_id: flow.id }, type)
                .then(() => {
                    if (request !== generation.current) return;
                    setOpen(false);
                    toast.show({ type: 'success', message: String(t('build.templateCreatedSuccessfully') ?? '') });
                    onCreated?.();
                }).catch(showApiError).finally(() => {
                    if (request === generation.current) {
                        pending.current = false;
                        setSubmitting(false);
                    }
                });
    };

    if (!canManageAppTemplates(user)) return null;

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className='sm:max-w-[625px]'>
                <DialogHeader>
                    <DialogTitle>{t('skills.createTemplate')}</DialogTitle>
                </DialogHeader>
                <div className='flex flex-col gap-4 py-2'>
                    <div className=''>
                        <label htmlFor='name' className='bisheng-label'>
                            {type === AppType.ASSISTANT ? t('build.assistantName') : t('build.workFlowName')}
                        </label>
                        <Input name='name' value={data.name} onChange={(e) => setData({ ...data, name: e.target.value })} className={"mt-2"} />
                    </div>
                    <div className=''>
                        <label htmlFor='roleAndTasks' className='bisheng-label'>
                            {t('skills.description')}
                        </label>
                        <Textarea id='name' value={data.description} onChange={(e) => setData({ ...data, description: e.target.value })} textareaClassName={"col-span-2"} />
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outlined" className='px-11' type='button' onClick={() => setOpen(false)} color="default">
                            {t('build.cancel')}
                        </Button>
                    </DialogClose>
                    <Button type='submit' className='px-11' disabled={submitting} onClick={handleSubmit}> {t('build.create')} </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
