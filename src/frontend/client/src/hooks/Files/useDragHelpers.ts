import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import type { DropTargetMonitor } from 'react-dnd';
import { useDrop } from 'react-dnd';
import { NativeTypes } from 'react-dnd-html5-backend';
import { useRecoilValue } from 'recoil';
import { File_Accept } from '~/common';
import { useGetBsConfig } from '~/data-provider';
import type * as t from '~/data-provider/data-provider/src';
import {
  AgentCapabilities,
  EModelEndpoint,
  isAgentsEndpoint,
  QueryKeys,
} from '~/data-provider/data-provider/src';
import store from '~/store';
import useFileHandling from './useFileHandling';
import { useToastContext } from '~/Providers';
import useLocalize from '../useLocalize';

export default function useDragHelpers(isLingsi) {
  const queryClient = useQueryClient();
  const { handleFiles } = useFileHandling();
  const [showModal, setShowModal] = useState(false);
  const [draggedFiles, setDraggedFiles] = useState<File[]>([]);
  const conversation = useRecoilValue(store.conversationByIndex(0)) || undefined;
  const localize = useLocalize();

  const handleOptionSelect = (toolResource: string | undefined) => {
    handleFiles(draggedFiles, toolResource);
    setShowModal(false);
    setDraggedFiles([]);
  };

  const { data: bsConfig } = useGetBsConfig()
  const accept = useMemo(() => {
    return bsConfig?.enable_etl4lm
      ? File_Accept.Linsight_Etl4lm
      : File_Accept.Linsight
  }, [bsConfig])

  const isAgents = useMemo(
    () => isAgentsEndpoint(conversation?.endpoint),
    [conversation?.endpoint],
  );

  const { showToast } = useToastContext();
  const [{ canDrop, isOver }, drop] = useDrop(
    () => ({
      accept: [NativeTypes.FILE],
      drop(item: { files: File[] }) {
        console.log('drop', item.files);
        // Split the accepted file extensions
        const acceptedExtensions = accept
          ? accept.split(',')
            .map(ext => ext.trim().toLowerCase().replace(/^\./, ''))  // Normalize extensions (remove leading dots)
          : [];

        // Check if any file has an invalid extension  // TODO 迁移到src/utils/files.ts（267行）
        const invalidFiles = item.files.filter(file => {
          const fileExtension = file.name.split('.').pop()?.toLowerCase();
          return fileExtension && !acceptedExtensions.includes(fileExtension);
        });

        if (invalidFiles.length > 0) {
          const uniqueExtensions = [...new Set(
            invalidFiles
              .map(f => f.name.split('.').pop()?.toLowerCase())
              .filter(Boolean)
          )];
          showToast({ message: localize('com_unsupported_file_type') + uniqueExtensions.join(','), status: 'error' });
          return;
        }
        if (!isAgents) {
          handleFiles(item.files);
          return;
        }

        const endpointsConfig = queryClient.getQueryData<t.TEndpointsConfig>([QueryKeys.endpoints]);
        const agentsConfig = endpointsConfig?.[EModelEndpoint.agents];
        const codeEnabled =
          agentsConfig?.capabilities?.includes(AgentCapabilities.execute_code) === true;
        const fileSearchEnabled =
          agentsConfig?.capabilities?.includes(AgentCapabilities.file_search) === true;
        if (!codeEnabled && !fileSearchEnabled) {
          handleFiles(item.files);
          return;
        }
        setDraggedFiles(item.files);
        setShowModal(true);
      },
      canDrop: () => true,
      collect: (monitor: DropTargetMonitor) => ({
        isOver: monitor.isOver(),
        canDrop: monitor.canDrop(),
      }),
    }),
    [isLingsi],
  );

  return {
    canDrop,
    isOver,
    drop,
    showModal,
    setShowModal,
    draggedFiles,
    handleOptionSelect,
  };
}
