import { getDshBrowserConfig } from '@/controllers/API/dshSettings'
import { DSH_BROWSER_CONFIG_CACHE_OPTIONS, DSH_BROWSER_CONFIG_QUERY_KEY } from '@bisheng/api-client'
import { useQuery } from '@tanstack/react-query'

export function useDshBrowserConfig() {
    const query = useQuery({
        queryKey: DSH_BROWSER_CONFIG_QUERY_KEY,
        queryFn: ({ signal }) => getDshBrowserConfig(signal),
        ...DSH_BROWSER_CONFIG_CACHE_OPTIONS,
    })
    return { config: query.data ?? null, failed: query.isError && !query.data }
}
