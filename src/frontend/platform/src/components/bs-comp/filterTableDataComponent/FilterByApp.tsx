import { Select } from '@bisheng/ui';
import { getGroupsApi } from '@/controllers/API/log';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelectLabels } from '../formFields/useSelectLabels';

interface AppOption {
    label: string;
    value: string;
}
interface AppResource {
    id?: string | number | null;
    name?: string | null;
}
interface FilterByAppProps {
    value: string[];
    placeholder?: string;
    onChange: (value: string[]) => void;
}
const PAGE_SIZE = 10;
function mapApps(data: AppResource[]): AppOption[] {
    return data.flatMap(item => item.id == null || item.id === '' ? [] : [{ label: String(item.name ?? item.id), value: String(item.id) }]);
}

export function FilterByApp({ value, placeholder, onChange }: FilterByAppProps) {
    const { t } = useTranslation();
    const labels = useSelectLabels();
    const { apps, loadApps, loadMoreApps } = useApps();
    const label = placeholder ?? t('log.appName');
    useEffect(() => { void loadApps(''); }, [loadApps]);

    return <Select {...labels} multiple showSearch filterOption={false}
        className="w-[200px]" panelClassName="max-w-[320px]"
        value={value} options={apps} placeholder={label} aria-label={label}
        onChange={values => onChange(values.map(String))}
        onSearch={loadApps} onLoadMore={loadMoreApps} />;
}
export default FilterByApp;

/** Preserve the existing application endpoint, page size and scroll-load contract. */
function useApps() {
    const [apps, setApps] = useState<AppOption[]>([]);
    const pageRef = useRef(1);
    const hasMoreRef = useRef(true);
    const loadLock = useRef(false);
    const keywordRef = useRef('');
    const abortControllerRef = useRef<AbortController>();

    const fetchData = useCallback(async (keyword: string, page: number): Promise<AppResource[]> => {
        abortControllerRef.current?.abort();
        abortControllerRef.current = new AbortController();
        try {
            // The legacy API declaration returns an array, but its actual envelope contains data.
            const response = await getGroupsApi({ keyword, page, page_size: PAGE_SIZE }, { signal: abortControllerRef.current.signal }) as unknown as { data: AppResource[] };
            return response.data;
        } catch (error) {
            if (error instanceof Error && error.name === 'AbortError') return [];
            throw error;
        }
    }, []);

    const loadApps = useCallback(async (keyword: string) => {
        if (loadLock.current) return;
        loadLock.current = true;
        keywordRef.current = keyword;
        try {
            const data = await fetchData(keyword, 1);
            setApps(mapApps(data));
            pageRef.current = 1;
            hasMoreRef.current = data.length === PAGE_SIZE;
        } catch (error) {
            console.error('Failed to load applications', error);
        } finally {
            loadLock.current = false;
        }
    }, [fetchData]);

    const loadMoreApps = useCallback(async () => {
        if (!hasMoreRef.current || loadLock.current) return;
        loadLock.current = true;
        try {
            const nextPage = pageRef.current + 1;
            const data = await fetchData(keywordRef.current, nextPage);
            setApps(previous => [...previous, ...mapApps(data)]);
            pageRef.current = nextPage;
            hasMoreRef.current = data.length === PAGE_SIZE;
        } catch (error) {
            console.error('Failed to load more applications', error);
        } finally {
            loadLock.current = false;
        }
    }, [fetchData]);

    useEffect(() => () => abortControllerRef.current?.abort(), []);
    return { apps, loadApps, loadMoreApps };
}
