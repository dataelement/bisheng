// hooks/useSopManagement.ts
import { useState, useEffect, useCallback } from 'react';
import { sopApi } from "@/controllers/API/linsight"
import { toast } from '@/components/bs-ui/toast/use-toast';

export const useSopManagement = () => {
  const [keywords, setKeywords] = useState('');
  const [datalist, setDatalist] = useState([]);
  const [total, setTotal] = useState(1);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [selectedItems, setSelectedItems] = useState([]);
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });
  const [isBatchDeleteModalOpen, setIsBatchDeleteModalOpen] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [currentSopId, setCurrentSopId] = useState(null);
  const [sopForm, setSopForm] = useState({
    id: '',
    name: '',
    description: '',
    content: '',
    rating: 0
  });

  const fetchData = useCallback(async (params = {}) => {
    setLoading(true);
    try {
      const res = await sopApi.getSopList({
        page_size: params.pageSize || pageSize,
        page: params.page || page,
        keywords: params.keyword || keywords
      });
      
      setDatalist(res.items || []);
      const hasItems = res.items && res.items.length > 0;
      const calculatedTotal = hasItems ? Math.max(res.total || 0, (params.page || page) * pageSize) : 0;
      setTotal(calculatedTotal);
    } catch (error) {
      console.error('请求失败:', error);
      toast({ variant: 'error', description: '搜索失败，请稍后重试' });
    } finally {
      setLoading(false);
    }
  }, [keywords, page, pageSize]);

  // 其他操作函数...

  return {
    keywords, setKeywords,
    datalist, setDatalist,
    total, setTotal,
    loading, setLoading,
    page, setPage,
    pageSize,
    selectedItems, setSelectedItems,
    sortConfig, setSortConfig,
    isBatchDeleteModalOpen, setIsBatchDeleteModalOpen,
    isDrawerOpen, setIsDrawerOpen,
    isEditing, setIsEditing,
    currentSopId, setCurrentSopId,
    sopForm, setSopForm,
    fetchData,
    // 其他返回的函数...
  };
};