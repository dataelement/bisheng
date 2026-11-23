import { Button, toast } from '@bisheng/ui';
import { useContext, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { userContext } from '@/contexts/userContext';
import { getToolsApi, updateToolApi } from '@/controllers/API/tools';
import { showApiError } from '@/controllers/request';
import { managementRequestScope } from '@/controllers/managementScope';
import ImageGeneration from '@/pages/BuildPage/tools/builtInTool/ImageGeneration';
import WebSearchForm from '@/pages/BuildPage/tools/builtInTool/WebSearchFrom';

type ToolKey = 'web_search' | 'image_generation';
type SavedTool = {
    id: string | number;
    extra: string | null;
    children?: { tool_key?: string }[];
};
type ToolEditor = { key: ToolKey; id: string | number; config: Record<string, unknown> };
interface SharedToolSettingsProps {
    disabled?: boolean;
}

export function SharedToolSettings({ disabled = false }: SharedToolSettingsProps) {
    const { t } = useTranslation('model');
    const { user } = useContext(userContext);
    const [editor, setEditor] = useState<ToolEditor | null>(null);
    const [busy, setBusy] = useState(false);
    const busyRef = useRef(false);
    const labels: Record<ToolKey, string> = {
        web_search: t('model.searchTool'),
        image_generation: t('model.drawingTool'),
    };

    const handleOpen = async (key: ToolKey) => {
        if (busyRef.current || !user?.is_global_super) return;
        busyRef.current = true;
        setBusy(true);
        try {
            const tools: SavedTool[] = await getToolsApi('default', { action: 'visible' });
            const matches = tools.filter((tool) => tool.children?.some((child) =>
                child.tool_key === key || (key === 'image_generation' && child.tool_key === 'dalle_image_generator')));
            if (matches.length !== 1 || !matches[0].id) {
                throw new Error(t('model.sharedToolUnavailable'));
            }
            const tool = matches[0];
            let config: unknown;
            try {
                config = tool.extra ? JSON.parse(tool.extra) : {};
            } catch {
                throw new Error(t('model.sharedToolUnavailable'));
            }
            if (!config || typeof config !== 'object' || Array.isArray(config)) {
                throw new Error(t('model.sharedToolUnavailable'));
            }
            setEditor({ key, id: tool.id, config: config as Record<string, unknown> });
        } catch (error) {
            showApiError(error);
        } finally {
            busyRef.current = false;
            setBusy(false);
        }
    };

    const handleSubmit = async (config: Record<string, unknown>) => {
        if (!editor || busyRef.current || !user?.is_global_super) return;
        busyRef.current = true;
        setBusy(true);
        try {
            await updateToolApi(editor.id, config);
            toast.show({ type: 'success', message: t('model.saveSuccess') });
            setEditor(null);
        } catch (error) {
            showApiError(error);
        } finally {
            busyRef.current = false;
            setBusy(false);
        }
    };

    if (!user?.is_global_super || (managementRequestScope() !== null && managementRequestScope() !== 1)) return null;

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted-foreground">{t('model.sharedToolHint')}</p>
            {(['web_search', 'image_generation'] as const).map((key) => (
                <div key={key} className="flex items-center justify-between gap-4">
                    <span className="bisheng-label">{labels[key]}</span>
                    <Button
                        type="button"
                        variant="outlined"
                        color="default"
                        disabled={disabled || busy}
                        aria-label={t('model.configureTool', { tool: labels[key] })}
                        onClick={() => void handleOpen(key)}
                    >
                        {t('model.configure')}
                    </Button>
                </div>
            ))}
            <Dialog open={!!editor} onOpenChange={(open) => { if (!open && !busyRef.current) setEditor(null); }}>
                <DialogContent className="sm:max-w-[625px] bg-background-login">
                    <DialogHeader>
                        <DialogTitle>{editor ? labels[editor.key] : ''}</DialogTitle>
                    </DialogHeader>
                    {editor && (
                        <fieldset disabled={busy} aria-busy={busy} className="min-w-0">
                            {editor.key === 'web_search'
                                ? <WebSearchForm
                                    toolId={String(editor.id)}
                                    onSaved={() => setEditor(null)}
                                    onSavingChange={(saving) => { busyRef.current = saving; setBusy(saving); }}
                                />
                                : <ImageGeneration formData={editor.config} onSubmit={handleSubmit} />}
                        </fieldset>
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
}
