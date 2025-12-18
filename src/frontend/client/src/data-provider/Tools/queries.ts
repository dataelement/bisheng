import { useQuery } from '@tanstack/react-query';
import { Constants, QueryKeys, dataService } from '~/data-provider/data-provider/src';
import type { QueryObserverResult, UseQueryOptions } from '@tanstack/react-query';
import type t from '~/data-provider/data-provider/src';
import { getKnowledgeInfo, getLinsightTools, getPersonalKnowledgeInfo } from '~/api/linsight';

export const useVerifyAgentToolAuth = (
  params: t.VerifyToolAuthParams,
  config?: UseQueryOptions<t.VerifyToolAuthResponse>,
): QueryObserverResult<t.VerifyToolAuthResponse> => {
  return useQuery<t.VerifyToolAuthResponse>(
    [QueryKeys.toolAuth, params.toolId],
    () => dataService.getVerifyAgentToolAuth(params),
    {
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchOnMount: false,
      ...config,
    },
  );
};

export const useGetToolCalls = <TData = t.ToolCallResults>(
  params: t.GetToolCallParams,
  config?: UseQueryOptions<t.ToolCallResults, unknown, TData>,
): QueryObserverResult<TData, unknown> => {
  const { conversationId = '' } = params;
  return useQuery<t.ToolCallResults, unknown, TData>({
    queryKey: [QueryKeys.toolCalls, conversationId],
    queryFn: () => dataService.getToolCalls(params),
    ...{
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchOnMount: false,
      enabled:
        conversationId.length > 0 &&
        conversationId !== Constants.NEW_CONVO &&
        conversationId !== Constants.SEARCH,
      ...config,
    },
  });
};


// 灵思内置工具列表
export const useGetLinsightToolList = () => {
  return useQuery({
    queryKey: ['LinsightTools'],
    queryFn: getLinsightTools,
    select(data) {
      return data?.data;
    },
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: false,
  });
}

// 获取个人知识库工具
export const useGetPersonalToolList = () => {
  return useQuery({
    queryKey: ['PersonalTools'],
    queryFn: () => getPersonalKnowledgeInfo(),
    select(data) {
      return data?.data;
    },
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

// 获取组织知识库
export const useGetOrgToolList = (query: { page, page_size?, name?}) => {
  return useQuery({
    queryKey: ['OrgTools', query.page, query.name],
    queryFn: () => getKnowledgeInfo(query),
    select(data) {
      return data?.data.data;
    },
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}