import { memo, useEffect, useMemo, useState } from 'react';
import { useRecoilValue } from 'recoil';
import {
  supportsFiles,
  mergeFileConfig,
  isAgentsEndpoint,
  EndpointFileConfig,
  fileConfig as defaultFileConfig,
} from '~/data-provider/data-provider/src';
import { useGetFileConfig } from '~/data-provider';
import AttachFileMenu from './AttachFileMenu';
import { useChatContext } from '~/Providers';
import { useFileHandling } from '~/hooks';
import AttachFile from './AttachFile';
import FileRow from './FileRow';
import store from '~/store';

function FileFormWrapper({
  children,
  disableInputs,
  disabledSearch,
  noUpload = false
}: {
  disableInputs: boolean;
  children?: React.ReactNode;
  disabledSearch: boolean;
  noUpload: boolean;
}) {
  const [fileTotalTokens, setFileTotalTokens] = useState(0);
  const chatDirection = useRecoilValue(store.chatDirection).toLowerCase();
  const { files, setFiles, conversation, setFilesLoading } = useChatContext();
  const { endpoint: _endpoint, endpointType } = conversation ?? { endpoint: null };
  const isAgents = useMemo(() => isAgentsEndpoint(_endpoint), [_endpoint]);

  const { handleFileChange, abortUpload } = useFileHandling();

  const { data: fileConfig = defaultFileConfig } = useGetFileConfig({
    select: (data) => mergeFileConfig(data),
  });

  const isRTL = chatDirection === 'rtl';

  const endpointFileConfig = fileConfig.endpoints[_endpoint ?? ''] as
    | EndpointFileConfig
    | undefined;

  const endpointSupportsFiles: boolean = supportsFiles[endpointType ?? _endpoint ?? ''] ?? false;
  const isUploadDisabled = (disableInputs || endpointFileConfig?.disabled) ?? false;

  const renderAttachFile = () => {
    if (isAgents) {
      return (
        <AttachFileMenu
          isRTL={isRTL}
          disabled={disableInputs}
          handleFileChange={handleFileChange}
        />
      );
    }
    if (endpointSupportsFiles && !isUploadDisabled) {
      return (
        <AttachFile
          isRTL={isRTL}
          disabled={disableInputs || disabledSearch}
          handleFileChange={handleFileChange}
        />
      );
    }

    return null;
  };
  useEffect(() => {
    let total = 0;
    files.forEach((item: any) => {
      total = item?.token + total;
    });
    setFileTotalTokens(total);
  }, [files]);

  if (noUpload) return children

  return (
    <>
      {files.size > 0 && <span className="pl-6 pt-2 text-sm">仅识别附件中的文字</span>}
      {fileTotalTokens > 0 && <span className="pl-6 pt-2 text-sm">文件内容超出3万token</span>}
      <FileRow
        files={files}
        setFiles={setFiles}
        abortUpload={abortUpload}
        setFilesLoading={setFilesLoading}
        isRTL={isRTL}
        Wrapper={({ children }) => <div className="mx-2 mt-2 flex flex-wrap gap-2">{children}</div>}
      />
      {children}
      {renderAttachFile()}
    </>
  );
}

export default memo(FileFormWrapper);
