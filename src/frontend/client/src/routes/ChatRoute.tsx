import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useToastContext } from '~/Providers';
import ChatView from '~/components/Chat/ChatView';
import { Spinner } from '~/components/svg';
import {
  useGetEndpointsQuery,
  useGetStartupConfig,
  useHealthCheck,
} from '~/data-provider';
import { useGetModelsQuery } from '~/data-provider/data-provider/src/react-query';
import { useAppStartup, useLocalize } from '~/hooks';
import useAuthRedirect from './useAuthRedirect';


export default function ChatRoute() {
  useErrorPrompt();

  useHealthCheck();
  const { data: startupConfig } = useGetStartupConfig();
  const { isAuthenticated, user } = useAuthRedirect();

  useAppStartup({ startupConfig, user });

  const { conversationId = 'new' } = useParams();

  const modelsQuery = useGetModelsQuery({
    enabled: isAuthenticated,
    refetchOnMount: 'always',
  });
  const endpointsQuery = useGetEndpointsQuery({ enabled: isAuthenticated });

  if (endpointsQuery.isLoading || modelsQuery.isLoading) {
    return (
      <div aria-live="polite" role="status">
        <Spinner className="m-auto text-black dark:text-white" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return <ChatView />;
}


const useErrorPrompt = () => {
  const search = location.search;
  const params = new URLSearchParams(search);
  const error = params.get('error');
  const { showToast } = useToastContext();
  const localize = useLocalize();

  useEffect(() => {
    if (error) {
      showToast({ message: localize(`api_errors.${error}`), status: 'error' });
    }
  }, []);
};