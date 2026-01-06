
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { publishDashboard } from "@/controllers/API/dashboard";
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

    const mutation = useMutation({
        mutationFn: ({ id, published }: { id: string; published: boolean }) =>
            publishDashboard(
                id,
                published ? DashboardStatus.Draft : DashboardStatus.Published
            ),
        onSuccess: (_, variables) => {
            queryClient.invalidateQueries({ queryKey: [DashboardsQueryKey] });
            toast({
                description: variables.published ? "已取消发布" : "已发布",
                variant: "success"
            });
        },
        onError: (error) => {
            console.error("Publish Error:", error);
            toast({
                description: "操作失败",
                variant: "error",
            });
        },
    });

    // 封装最终调用的方法
    const handlePublish = (id: string, published: boolean) => {
        mutation.mutate({ id, published });
    };

    return {
        publish: handlePublish,
        isPublishing: mutation.isLoading,
        mutation,
    };
};