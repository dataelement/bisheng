import { Button, Tag } from '@bisheng/ui';
import { useQuery } from '@tanstack/react-query';
import { useContext } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { LoadingIcon } from '@/components/bs-icons/loading';
import { userContext } from '@/contexts/userContext';
import { getWorkflowManagementSummary } from '@/controllers/API/flow';
import { WORKFLOW_MANAGEMENT_PATH } from '@/utils/workflowManagement';

export function WorkflowManagementDetail() {
    const { id = '' } = useParams();
    const { user } = useContext(userContext);
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { data, isInitialLoading, isFetching, isError, refetch } = useQuery({
        queryKey: ['workflowManagementDetail', user?.user_id, user?.tenant_id, id],
        queryFn: () => getWorkflowManagementSummary(id),
        refetchOnMount: 'always',
        retry: false,
    });

    return <section className="p-10">
        <Button variant="outlined" onClick={() => navigate(WORKFLOW_MANAGEMENT_PATH)}>
            {t('build.workflowManagement')}
        </Button>
        {(isInitialLoading || isFetching) ? <LoadingIcon /> : isError ? (
            <Button className="mt-5" variant="outlined" onClick={() => void refetch()}>
                {t('build.reloadWorkflows')}
            </Button>
        ) : data && (
            <div className="mt-5 p-6 bg-background-main rounded-lg">
                <h1 className="text-xl font-semibold">{data.name}</h1>
                <div className="flex gap-2 mt-2">
                    <Tag size="small" color="default">{t('build.workflowReadOnly')}</Tag>
                    <Tag size="small" color="default">{t(data.status === 2 ? 'build.online' : 'build.offline')}</Tag>
                </div>
                {data.description && <p className="mt-4 whitespace-pre-wrap">{data.description}</p>}
                {data.versions.length > 0 && <ul className="mt-4 space-y-1">
                    {data.versions.map(version => <li key={version.id}>{version.name}</li>)}
                </ul>}
            </div>
        )}
    </section>;
}
