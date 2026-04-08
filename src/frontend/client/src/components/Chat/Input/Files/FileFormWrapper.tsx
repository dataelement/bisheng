import { memo, useEffect, useState } from "react";
import { useRecoilValue } from "recoil";
import { useChatContext } from "~/Providers";
import { useGetFileConfig } from "~/data-provider";
import {
  EndpointFileConfig,
  fileConfig as defaultFileConfig,
  mergeFileConfig
} from "~/data-provider/data-provider/src";
import { useFileHandling } from "~/hooks";
import useLocalize from "~/hooks/useLocalize";
import store from "~/store";
import AttachFile from "./AttachFile";
import FileRow from "./FileRow";

function FileFormWrapper({
  children,
  accept = "",
  fileTip = false,
  disableInputs,
  disabledSearch,
  noUpload = false,
  showVoice = false
}: {
  disableInputs: boolean;
  children?: React.ReactNode;
  disabledSearch: boolean;
  fileTip?: boolean;
  accept?: string;
  noUpload: boolean;
  showVoice?: boolean;
}) {
  const t = useLocalize();
  const [fileTotalTokens, setFileTotalTokens] = useState(0);
  const chatDirection = useRecoilValue(store.chatDirection).toLowerCase();
  const { files, setFiles, conversation, setFilesLoading } = useChatContext();
  const { endpoint: _endpoint, endpointType } = conversation ?? {
    endpoint: null,
  };

  const { handleFileChange, abortUpload } = useFileHandling({
    isLinsight: !fileTip,
  });

  const { data: fileConfig = defaultFileConfig } = useGetFileConfig({
    select: (data) => mergeFileConfig(data),
  });

  const isRTL = chatDirection === "rtl";

  const endpointFileConfig = fileConfig.endpoints[_endpoint ?? ""] as
    | EndpointFileConfig
    | undefined;

  const renderAttachFile = () => {
    // if (isAgents) {
    //   return (
    //     <AttachFileMenu
    //       isRTL={isRTL}
    //       disabled={disableInputs}
    //       handleFileChange={handleFileChange}
    //     />
    //   );
    // }
    // if (endpointSupportsFiles) {
    // this
    return (
      <AttachFile
        isRTL={isRTL}
        showVoice={showVoice}
        accept={accept}
        disabled={disableInputs || disabledSearch}
        handleFileChange={handleFileChange}
      />
    );
    // }

    return null;
  };
  useEffect(() => {
    let total = 0;
    files.forEach((item: any) => {
      total = item?.token + total;
    });
    setFileTotalTokens(total);
  }, [files]);

  if (noUpload) return children;

  return (
    <>
      {fileTip && files.size > 0 && (
        <span className="pl-6 pt-2 text-sm">{t("com_file_tip_text_only")}</span>
      )}
      {fileTotalTokens > 0 && (
        <span className="pl-6 pt-2 text-sm">
          {t("com_file_content_exceed_tokens")}
        </span>
      )}

      <FileRow
        files={files}
        setFiles={setFiles}
        abortUpload={abortUpload}
        setFilesLoading={setFilesLoading}
        isRTL={isRTL}
        Wrapper={({ children }) => (
          <div className="mx-2 mt-2 flex flex-wrap gap-2 max-h-96 overflow-auto">
            {children}
          </div>
        )}
      />
      {children}
      {/* 上传按钮 */}
      {renderAttachFile()}
    </>
  );
}

export default memo(FileFormWrapper);
