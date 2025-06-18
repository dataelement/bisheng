import { useState, useEffect } from 'react';
import { getKnowledgeDetailApi } from '../API';

/**
 * 获取知识库详情的自定义 Hook
 * @param {string[]} [knowledgeIds] - 知识库 ID 数组（可选）
 * @returns {[Array, Function]} - 返回 [知识库详情数据, 手动请求函数]
 */
export const useKnowledgeDetails = (knowledgeIds) => {
    const [details, setDetails] = useState([]);

    // 请求知识库详情的函数
    const fetchDetails = async (ids) => {
        if (!ids?.length) return;
        try {
            const res = await getKnowledgeDetailApi(ids);
            setDetails(res);
        } catch (error) {
            console.error('获取知识库详情失败:', error);
            setDetails([]); // 失败时清空数据
        }
    };

    // 自动请求（当 knowledgeIds 变化时）
    useEffect(() => {
        fetchDetails(knowledgeIds);
    }, []);

    return [details, fetchDetails];
};