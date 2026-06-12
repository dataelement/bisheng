// F035: create / edit a tenant custom skill (form path — SKILL.md only).
// The skill ID is auto-suggested from the display name via the backend
// pypinyin helper (single source of truth with the SOP migration script).
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { SkillDetail, skillApi } from "@/controllers/API/linsight";
import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { getSkillErrorMessage } from "./skillErrors";

const SKILL_ID_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;

interface SkillFormDrawerProps {
    open: boolean;
    /** null = create mode; a detail = edit mode (skill ID is immutable) */
    editing: SkillDetail | null;
    onOpenChange: (open: boolean) => void;
    onSaved: () => void;
}

type FieldErrors = Partial<Record<'displayName' | 'name' | 'description' | 'content', string>>;

export function SkillFormDrawer({ open, editing, onOpenChange, onSaved }: SkillFormDrawerProps) {
    const { t } = useTranslation();
    const [displayName, setDisplayName] = useState('');
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [content, setContent] = useState('');
    const [errors, setErrors] = useState<FieldErrors>({});
    const [saving, setSaving] = useState(false);
    // Once the admin edits the skill ID by hand, stop auto-suggesting.
    const idTouchedRef = useRef(false);
    const slugTimerRef = useRef<ReturnType<typeof setTimeout>>();

    useEffect(() => {
        if (!open) return;
        idTouchedRef.current = false;
        setErrors({});
        if (editing) {
            setDisplayName(editing.display_name);
            setName(editing.name);
            setDescription(editing.description);
            setContent(editing.preview);
        } else {
            setDisplayName('');
            setName('');
            setDescription('');
            setContent('');
        }
    }, [open, editing]);

    const requestSlug = (text: string) => {
        clearTimeout(slugTimerRef.current);
        if (!text.trim()) return;
        slugTimerRef.current = setTimeout(() => {
            skillApi.slugify(text).then((res) => {
                if (!idTouchedRef.current) setName(res.slug);
            }).catch(() => { /* suggestion only — typing manually still works */ });
        }, 400);
    };

    const handleDisplayNameChange = (value: string) => {
        setDisplayName(value);
        setErrors(prev => ({ ...prev, displayName: undefined }));
        if (!editing && !idTouchedRef.current) requestSlug(value);
    };

    const handleNameChange = (value: string) => {
        idTouchedRef.current = true;
        setName(value);
        setErrors(prev => ({ ...prev, name: undefined }));
    };

    const handleRegenerate = () => {
        idTouchedRef.current = false;
        requestSlug(displayName);
    };

    const validate = (): boolean => {
        const next: FieldErrors = {};
        if (!displayName.trim()) next.displayName = t('skillManage.form.requiredField');
        const id = name.trim();
        if (!id) next.name = t('skillManage.form.requiredField');
        else if (id.length > 64) next.name = t('skillManage.form.idTooLong');
        else if (!SKILL_ID_RE.test(id)) next.name = t('skillManage.form.idInvalid');
        if (!description.trim()) next.description = t('skillManage.form.requiredField');
        if (!content.trim()) next.content = t('skillManage.form.requiredField');
        setErrors(next);
        return Object.keys(next).length === 0;
    };

    const handleSave = async () => {
        if (!validate() || saving) return;
        setSaving(true);
        const payload = {
            display_name: displayName.trim(),
            name: name.trim(),
            description: description.trim(),
            content,
        };
        try {
            if (editing) {
                await skillApi.updateSkillForm(editing.name, payload);
            } else {
                await skillApi.createSkillForm(payload);
            }
            toast({ variant: 'success', description: t('skillManage.saved') });
            onOpenChange(false);
            onSaved();
        } catch (err) {
            toast({ variant: 'error', description: getSkillErrorMessage(err, t) });
        } finally {
            setSaving(false);
        }
    };

    const fieldLabel = (label: string, desc: string) => (
        <div className="flex items-baseline gap-2 mb-1.5">
            <Label className="bisheng-label"><span className="text-red-500 mr-0.5">*</span>{label}</Label>
            <span className="text-xs text-muted-foreground">{desc}</span>
        </div>
    );

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[760px]">
                <DialogHeader>
                    <DialogTitle>{editing ? t('skillManage.edit') : t('skillManage.create')}</DialogTitle>
                </DialogHeader>
                <div className="grid gap-4 py-2 max-h-[64vh] overflow-y-auto pr-1">
                    <div>
                        {fieldLabel(t('skillManage.form.displayName'), t('skillManage.form.displayNameDesc'))}
                        <Input
                            value={displayName}
                            maxLength={255}
                            placeholder={t('skillManage.form.displayNamePh')}
                            onChange={(e) => handleDisplayNameChange(e.target.value)}
                        />
                        {errors.displayName && <p className="text-xs text-red-500 mt-1">{errors.displayName}</p>}
                    </div>
                    <div>
                        {fieldLabel(t('skillManage.form.skillId'), t('skillManage.form.skillIdDesc'))}
                        <div className="flex gap-2">
                            <Input
                                value={name}
                                maxLength={64}
                                disabled={!!editing}
                                className="font-mono"
                                placeholder={t('skillManage.form.skillIdPh')}
                                onChange={(e) => handleNameChange(e.target.value)}
                            />
                            {!editing && (
                                <Button variant="outline" size="sm" className="h-9 shrink-0" onClick={handleRegenerate}>
                                    <RefreshCw className="size-3.5 mr-1" />{t('skillManage.form.regenerate')}
                                </Button>
                            )}
                        </div>
                        {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name}</p>}
                    </div>
                    <div>
                        {fieldLabel(t('skillManage.form.description'), t('skillManage.form.descriptionDesc'))}
                        <Input
                            value={description}
                            maxLength={1024}
                            placeholder={t('skillManage.form.descriptionPh')}
                            onChange={(e) => { setDescription(e.target.value); setErrors(prev => ({ ...prev, description: undefined })); }}
                        />
                        {errors.description && <p className="text-xs text-red-500 mt-1">{errors.description}</p>}
                    </div>
                    <div>
                        {fieldLabel(t('skillManage.form.content'), t('skillManage.form.contentDesc'))}
                        <Textarea
                            value={content}
                            rows={10}
                            className="font-mono text-sm"
                            placeholder={t('skillManage.form.contentPh')}
                            onChange={(e) => { setContent(e.target.value); setErrors(prev => ({ ...prev, content: undefined })); }}
                        />
                        {errors.content && <p className="text-xs text-red-500 mt-1">{errors.content}</p>}
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>{t('skillManage.form.cancel')}</Button>
                    <Button onClick={handleSave} disabled={saving}>{t('skillManage.form.save')}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
