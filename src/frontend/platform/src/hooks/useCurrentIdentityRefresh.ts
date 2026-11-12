import { useQuery } from '@tanstack/react-query';
import { getUserInfo } from '@/controllers/API/user';

export interface CurrentIdentity {
    user_id: number;
    user_name: string;
    external_id?: string | null;
}

export function useCurrentIdentityRefresh(
    user: CurrentIdentity | null | undefined,
    onRefreshed: (identity: CurrentIdentity) => void,
) {
    const userId = user?.user_id ?? 0;
    useQuery<CurrentIdentity>({
        queryKey: ['current-user-identity', userId],
        enabled: userId > 0,
        initialData: user && userId > 0 ? user : undefined,
        staleTime: Infinity,
        refetchOnWindowFocus: 'always',
        refetchOnReconnect: false,
        retry: false,
        queryFn: async () => {
            const profile = await getUserInfo();
            if (profile.user_id !== userId) throw new Error('Current identity changed during profile refresh');
            return { user_id: profile.user_id, user_name: profile.user_name, external_id: profile.external_id ?? null };
        },
        onSuccess: onRefreshed,
    });
}
