import { getAllLabelsApi } from "@/controllers/API/label";
import { useMemo, useState } from "react";
import { useQuery } from 'react-query';

export const useQueryLabels = (t) => {
    const { data: options, refetch } = useQuery({
        queryKey: "QueryLabelsKey",
        queryFn: () => getAllLabelsApi().then(res =>
            res.data.map(d => ({ label: d.name, value: d.id, edit: false, selected: false }))
        )
    });

    const [searchKey, setSearchKey] = useState('');
    const [selectLabel, setSelectLabel] = useState({ label: '', value: null })

    const [filteredOptions, allOptions] = useMemo(() => {
        if (!options) return [[], []]
        const topItem = { label: t('all'), value: -1, edit: false, selected: false }
        if (!searchKey) return [options, [topItem, ...options]];
        // 检索
        const _newOptions = options.filter(op => op.label.toUpperCase().includes(searchKey.toUpperCase()) || op.value === selectLabel.value)
        return [_newOptions, [topItem, ..._newOptions]]
    }, [searchKey, options, selectLabel])

    return {
        selectLabel,
        setSelectLabel,
        setSearchKey,
        filteredOptions,
        allOptions,
        refetchLabels: refetch
    }
}