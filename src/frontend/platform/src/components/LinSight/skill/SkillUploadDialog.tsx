// F035: upload a skill as a single .md file or a .zip/.skill bundle
// (archive root must contain SKILL.md; whole bundle <= 10MB).
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { skillApi } from "@/controllers/API/linsight";
import { FileUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { getSkillErrorMessage } from "./skillErrors";

const ACCEPTED_SUFFIXES = ['.md', '.zip', '.skill'];
const MAX_BUNDLE_SIZE = 10 * 1024 * 1024;

interface SkillUploadDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onUploaded: () => void;
}

export function SkillUploadDialog({ open, onOpenChange, onUploaded }: SkillUploadDialogProps) {
    const { t } = useTranslation();
    const [file, setFile] = useState<File | null>(null);
    const [uploading, setUploading] = useState(false);

    useEffect(() => {
        if (open) setFile(null);
    }, [open]);

    const handleDrop = useCallback((accepted: File[]) => {
        const picked = accepted[0];
        if (!picked) return;
        const lower = picked.name.toLowerCase();
        if (!ACCEPTED_SUFFIXES.some(suffix => lower.endsWith(suffix))) {
            toast({ variant: 'error', description: t('skillManage.uploadDialog.unsupported') });
            return;
        }
        if (picked.size > MAX_BUNDLE_SIZE) {
            toast({ variant: 'error', description: t('skillManage.errors.tooLarge') });
            return;
        }
        setFile(picked);
    }, [t]);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop: handleDrop, multiple: false });

    const handleUpload = async () => {
        if (!file || uploading) return;
        setUploading(true);
        try {
            await skillApi.createSkillUpload(file);
            toast({ variant: 'success', description: t('skillManage.saved') });
            onOpenChange(false);
            onUploaded();
        } catch (err) {
            toast({ variant: 'error', description: getSkillErrorMessage(err, t) });
        } finally {
            setUploading(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[560px]">
                <DialogHeader>
                    <DialogTitle>{t('skillManage.upload')}</DialogTitle>
                </DialogHeader>
                <div
                    {...getRootProps()}
                    className={`border-2 border-dashed rounded-lg px-6 py-10 text-center cursor-pointer transition-colors ${isDragActive ? 'border-primary bg-primary/5' : 'border-border'}`}
                >
                    <input {...getInputProps()} />
                    <FileUp className="size-8 mx-auto text-muted-foreground" />
                    <p className="mt-2 text-sm">{file ? `${file.name} (${(file.size / 1024).toFixed(1)} KB)` : t('skillManage.uploadDialog.dropHint')}</p>
                    <p className="text-xs text-muted-foreground mt-1">{t('skillManage.uploadDialog.dropSub')}</p>
                </div>
                <div className="text-xs text-muted-foreground space-y-1">
                    <p className="font-medium text-foreground">{t('skillManage.uploadDialog.requirementsTitle')}</p>
                    <ul className="list-disc pl-4 space-y-0.5">
                        <li>{t('skillManage.uploadDialog.reqMd')}</li>
                        <li>{t('skillManage.uploadDialog.reqZip')}</li>
                        <li>{t('skillManage.uploadDialog.reqSize')}</li>
                    </ul>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>{t('skillManage.form.cancel')}</Button>
                    <Button onClick={handleUpload} disabled={!file || uploading}>{t('skillManage.uploadDialog.confirm')}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
