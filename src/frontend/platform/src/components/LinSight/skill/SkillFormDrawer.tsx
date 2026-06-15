// F035: create / edit a tenant custom skill (form path — SKILL.md only).
// Rendered as a right-side drawer on the same rail as the detail sheet, so
// opening edit from the detail reads as the panel turning over into its form
// (delete-confirm and upload stay centered modals). The skill ID is
// auto-suggested from the display name via the backend pypinyin helper.
import { Button } from "@/components/bs-ui/button";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Sheet, SheetContent } from "@/components/bs-ui/sheet";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { SkillDetail, skillApi } from "@/controllers/API/linsight";
import { Pencil, Plus, RefreshCw } from "lucide-react";
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
            // `preview` is the SKILL.md body without frontmatter — exactly what the
            // form-update path expects, since the backend regenerates frontmatter
            // from name/description/display_name via compose_skill_md.
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
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="sm:max-w-[680px] w-[92vw] p-0 gap-0 flex flex-col bg-background">
                {/* header — mirrors the detail sheet so edit reads as the panel flipping into its form */}
                <div className="shrink-0 flex items-start gap-3 px-6 py-5 pr-12 border-b">
                    <div className="size-9 mt-0.5 shrink-0 rounded-xl grid place-items-center text-primary bg-gradient-to-br from-[#EEF2FF] to-[#E2EAFF]">
                        {editing ? <Pencil className="size-[18px]" /> : <Plus className="size-5" />}
                    </div>
                    <div className="min-w-0">
                        <p className="text-[17px] font-semibold leading-tight text-foreground">
                            {editing ? t('skillManage.edit') : t('skillManage.create')}
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                            {editing ? t('skillManage.form.editSubtitle') : t('skillManage.form.createSubtitle')}
                        </p>
                    </div>
                </div>

                {/* body — top fields fixed, the SKILL.md body textarea fills remaining height */}
                <div className="flex-1 min-h-0 overflow-hidden flex flex-col gap-4 px-6 py-5">
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
                    {/* content — flexes to fill the full-height drawer, a tall calm authoring canvas */}
                    <div className="flex flex-col flex-1 min-h-0">
                        {fieldLabel(t('skillManage.form.content'), t('skillManage.form.contentDesc'))}
                        <Textarea
                            value={content}
                            boxClassName="flex-1 min-h-0"
                            className="h-full resize-none font-mono text-sm"
                            placeholder={t('skillManage.form.contentPh')}
                            onChange={(e) => { setContent(e.target.value); setErrors(prev => ({ ...prev, content: undefined })); }}
                        />
                        {errors.content && <p className="text-xs text-red-500 mt-1">{errors.content}</p>}
                    </div>
                </div>

                {/* footer — actions only */}
                <div className="shrink-0 flex items-center justify-end gap-3 px-6 py-3.5 border-t bg-background/90 backdrop-blur">
                    <Button variant="outline" onClick={() => onOpenChange(false)}>{t('skillManage.form.cancel')}</Button>
                    <Button onClick={handleSave} disabled={saving}>{t('skillManage.form.save')}</Button>
                </div>
            </SheetContent>
        </Sheet>
    );
}
