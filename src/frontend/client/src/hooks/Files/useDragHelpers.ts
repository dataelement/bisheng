import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import type { DropTargetMonitor } from 'react-dnd';
import { useDrop } from 'react-dnd';
import { NativeTypes } from 'react-dnd-html5-backend';
import { useRecoilValue } from 'recoil';
import type * as t from '~/data-provider/data-provider/src';
import {
  AgentCapabilities,
  EModelEndpoint,
  isAgentsEndpoint,
  QueryKeys,
} from '~/data-provider/data-provider/src';
import store from '~/store';
import useFileHandling from './useFileHandling';

export default function useDragHelpers(isLingsi) {
  const queryClient = useQueryClient();
  const { handleFiles } = useFileHandling();
  const [showModal, setShowModal] = useState(false);
  const [draggedFiles, setDraggedFiles] = useState<File[]>([]);
  const conversation = useRecoilValue(store.conversationByIndex(0)) || undefined;

  const handleOptionSelect = (toolResource: string | undefined) => {
    handleFiles(draggedFiles, toolResource);
    setShowModal(false);
    setDraggedFiles([]);
  };

  const isAgents = useMemo(
    () => isAgentsEndpoint(conversation?.endpoint),
    [conversation?.endpoint],
  );

  const [{ canDrop, isOver }, drop] = useDrop(
    () => ({
      accept: [NativeTypes.FILE],
      drop(item: { files: File[] }) {
        console.log('drop', item.files);
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
