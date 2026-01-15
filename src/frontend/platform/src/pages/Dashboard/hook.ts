
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { publishDashboard } from "@/controllers/API/dashboard";
import { useEditorDashboardStore } from "@/store/dashboardStore";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "react-query";

export const DashboardsQueryKey = "DashboardsQueryKey"
export const DashboardQueryKey = "DashboardQueryKey"
export const enum DashboardStatus {
    Draft = "draft",
    Published = "published",
}

export const usePublishDashboard = () => {
    const queryClient = useQueryClient();
    const { toast } = useToast();
    const { t } = useTranslation("dashboard")

    const mutation = useMutation({
        mutationFn: ({ id, published }: { id: string; published: boolean }) =>
            publishDashboard(
                id,
                published ? DashboardStatus.Draft : DashboardStatus.Published
            ),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: [DashboardQueryKey, variables.id] });
            queryClient.setQueryData([DashboardsQueryKey], (old) => {
                return old.map(el => el.id === variables.id ? {
                    ...el,
                    status: variables.published ? DashboardStatus.Draft : DashboardStatus.Published
                } : el);
            });
            toast({
                description: variables.published ? t('unpublishSuccess') : t('publishSuccess'),
                variant: "success"
            });
        },
        onError: (error) => {
            console.error("Publish Error:", error);
            toast({
                description: t('operationFailed'),
                variant: "error",
            });
        },
    });

    // publish function
    const handlePublish = (id: string, published: boolean) => {
        mutation.mutate({ id, published });
    };

    return {
        publish: handlePublish,
        isPublishing: mutation.isLoading,
        mutation,
    };
};

export const useEditorShortcuts = () => {
    const { undo, redo, history } = useEditorDashboardStore();

    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            const isCtrlOrCmd = event.ctrlKey || event.metaKey;

            // Undo: Ctrl + Z
            if (isCtrlOrCmd && !event.shiftKey && event.key.toLowerCase() === 'z') {
                event.preventDefault();
                if (history.past.length > 0) undo();
            }

            // Redo: Ctrl + Shift + Z or Ctrl + Y
            if (
                (isCtrlOrCmd && event.shiftKey && event.key.toLowerCase() === 'z') ||
                (isCtrlOrCmd && event.key.toLowerCase() === 'y')
            ) {
                event.preventDefault();
                if (history.future.length > 0) redo();
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [undo, redo, history.past.length, history.future.length]);
};
