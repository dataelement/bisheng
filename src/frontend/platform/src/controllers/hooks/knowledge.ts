// @ts-strict-ignore
import { useState, useEffect } from 'react';
import { getKnowledgeDetailApi } from '../API';

// Keep failed detail requests rejected so dependent mutations cannot use empty data.
export const useKnowledgeDetails = (knowledgeIds) => {
    const [details, setDetails] = useState([]);
    const [error, setError] = useState<unknown>(null);

    const fetchDetails = async (ids) => {
        if (!ids?.length) return [];
        const res = await getKnowledgeDetailApi(ids);
        setDetails(res);
        setError(null);
        return res;
    };

    // Preserve the original initial failure as state; the creation action can retry.
    useEffect(() => {
        void fetchDetails(knowledgeIds).catch(setError);
    }, []);

    return [details, fetchDetails, error] as const;
};
