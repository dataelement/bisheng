import { useToast } from "@/components/bs-ui/toast/use-toast";
import { getAllLabelsApi } from "@/controllers/API/label";
import { AppType } from "@/types/app";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
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


// 创建技能模板弹窗状态
export const useCreateTemp = () => {
    const [open, setOpen] = useState(false)
    const [tempType, setType] = useState<AppType>(AppType.ALL)
    const flowRef = useRef(null)

    return {
        open,
        tempType,
        flowRef,
        toggleTempModal(flow?) {
            const map = { 10: "flow", 5: "assistant", 1: "skill" }
            flowRef.current = flow || null
            flow && setType(map[flow.flow_type])
            setOpen(!open)
        }
    }
}

export const useErrorPrompt = () => {
    const search = location.search;
    const params = new URLSearchParams(search);
    const error = params.get('error');
    const { toast } = useToast()
    const { t } = useTranslation()

    useEffect(() => {
        if (error) {
            toast({ description: t(`errors.${error}`), variant: 'error' });

            // Clear the 'error' parameter from the URL
            const newUrl = window.location.origin + window.location.pathname;
            window.history.replaceState({}, '', newUrl);
        }
    }, [])
}
