import { Button, Switch, Tooltip, notification, toast } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { AccordionContent, AccordionItem, AccordionTrigger } from '@/components/bs-ui/accordion';
import { Sheet, SheetContent, SheetTitle } from '@/components/bs-ui/sheet';
import { getSensitiveApi, sensitiveSaveApi } from '@/controllers/API/pro';
import { showApiError } from '@/controllers/request';
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import FormSet from './FormSet';
import FormView from './FormView';

interface AssistantSettingProps {
    id: string | number;
    type: string | number;
}

export interface AssistantSettingRef {
    create: (id: number) => Promise<boolean>;
}

type SecurityForm = { isCheck: boolean; autoReply: string; words: string; wordsType: number[] };
const EMPTY_FORM: SecurityForm = { isCheck: false, autoReply: '', words: '', wordsType: [] };

function validationErrors(form: SecurityForm): string[] {
    const errors: string[] = [];
    if (!form.wordsType.length) errors.push('build.errors.selectAtLeastOneWordType');
    if (!form.autoReply.trim()) errors.push('build.errors.autoReplyNotEmpty');
    if (form.autoReply.length > 500) errors.push('build.errors.workbenchAutoReplyMaxLength');
    if (form.wordsType.includes(2) && !form.words.trim()) errors.push('build.errors.customWordsNotEmpty');
    return errors;
}

const AssistantSetting = forwardRef<AssistantSettingRef, AssistantSettingProps>(({ id, type }, ref) => {
    const { t } = useTranslation();
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState<SecurityForm>(EMPTY_FORM);
    const [draft, setDraft] = useState<SecurityForm>(EMPTY_FORM);
    const [loading, setLoading] = useState(Boolean(id && id !== 3));
    const [pending, setPending] = useState(false);
    const saving = useRef(false);

    useEffect(() => {
        let active = true;
        setOpen(false);
        setForm(EMPTY_FORM);
        if (!id || id === 3) {
            setLoading(false);
            return;
        }
        setLoading(true);
        getSensitiveApi(id, type).then(res => {
            if (!active) return;
            const rawTypes: unknown[] = Array.isArray(res.words_type) ? res.words_type : [res.words_type];
            setForm({
                isCheck: Boolean(res.is_check),
                autoReply: typeof res.auto_reply === 'string' ? res.auto_reply : '',
                words: typeof res.words === 'string' ? res.words : '',
                wordsType: [...new Set(rawTypes.map(Number).filter((value): value is number => value === 1 || value === 2))],
            });
            setLoading(false);
        }).catch(error => {
            if (active) showApiError(error);
        });
        return () => { active = false; };
    }, [id, type]);

    const validateForm = (next: SecurityForm) => {
        const errors = validationErrors(next);
        if (!errors.length) return true;
        notification.open({ type: 'error', title: String(t('prompt')), description: errors.map(key => t(key)).join(', ') });
        return false;
    };

    const persist = async (next: SecurityForm, saveId: string | number = id) => {
        if (saving.current || loading) return false;
        saving.current = true;
        setPending(true);
        try {
            if (saveId) await sensitiveSaveApi({ ...next, id: saveId, type });
            setForm(next);
            return true;
        } catch (error) {
            showApiError(error);
            return false;
        } finally {
            saving.current = false;
            setPending(false);
        }
    };

    useImperativeHandle(ref, () => ({
        create: async (saveId: number) => {
            if (loading || saving.current) return false;
            if (!form.isCheck) return true;
            return validateForm(form) && await persist(form, saveId);
        },
    }));

    const openEditor = () => {
        if (loading || saving.current) return;
        setDraft({ ...form, isCheck: true, wordsType: [...form.wordsType] });
        setOpen(true);
    };

    const handleFormChange = async (next: SecurityForm) => {
        const enabled = { ...next, isCheck: true };
        if (!validateForm(enabled)) return true;
        const saved = await persist(enabled);
        if (saved && id) {
            toast.show({ type: 'success', message: String(t('build.saveSuccess')) });
        }
        // FormSet closes only when its submit callback reports no blocking error.
        return !saved;
    };

    const onOff = async (enabled: boolean) => {
        if (loading || saving.current) return;
        if (enabled && validationErrors(form).length) {
            openEditor();
            return;
        }
        await persist({ ...form, isCheck: enabled });
    };

    return (
        <AccordionItem value="item-3">
            <div className="flex items-center justify-between">
                <AccordionTrigger className="flex-1">
                    <div className="flex items-center space-x-2">
                        <span>{t('build.contentSecurityR')}</span>
                        <Tooltip content={t('build.contentSecurityDesc')}>
                            <span className="inline-flex" tabIndex={0}><Outlined.Question className="size-4" /></span>
                        </Tooltip>
                    </div>
                </AccordionTrigger>
                <div className="flex items-center">
                    {form.isCheck && <Button variant="text" color="default" size="small" iconOnly
                        aria-label={t('build.contentSecuritySettings')} disabled={loading || pending}
                        onClick={event => { event.stopPropagation(); openEditor(); }}>
                        <Outlined.Setting className="size-4" />
                    </Button>}
                    <Sheet open={open} onOpenChange={next => { if (!saving.current) setOpen(next); }}>
                        <SheetContent className="w-[500px]" onClick={event => event.stopPropagation()}>
                            <SheetTitle className="font-[500] pl-3 pt-2">{t('build.contentSecuritySettings')}</SheetTitle>
                            <FormSet data={draft} onChange={handleFormChange} onSave={() => setOpen(false)} onCancel={() => setOpen(false)} />
                        </SheetContent>
                    </Sheet>
                    <Switch className="mx-4" aria-label={t('build.contentSecurityR')} disabled={loading || pending}
                        onClick={event => event.stopPropagation()} checked={form.isCheck} onCheckedChange={onOff} />
                </div>
            </div>
            <AccordionContent className="mb-[-16px]">
                {form.isCheck && <FormView data={form} />}
            </AccordionContent>
        </AccordionItem>
    );
});

AssistantSetting.displayName = 'AssistantSetting';
export default AssistantSetting;
