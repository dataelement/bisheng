import { Rotate3DIcon, Spline } from 'lucide-react';
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { Button, TextareaAutosize } from '~/components/ui';
import { Select, SelectContent, SelectItem, SelectTrigger } from '~/components/ui/Select';
import { useGetBsConfig, useGetFileConfig, useGetUserLinsightCountQuery } from '~/data-provider';
import {
  BsConfig,
  fileConfig as defaultFileConfig,
  isAssistantsEndpoint,
  mergeFileConfig,
  supportsFiles,
} from '~/data-provider/data-provider/src';
import {
  useAutoSave,
  useHandleKeyUp,
  useLocalize,
  useQueryParams,
  useRequiresKey,
  useSubmitMessage,
  useTextarea,
} from '~/hooks';
import {
  useAddedChatContext,
  useAssistantsMapContext,
  useChatContext,
  useChatFormContext,
} from '~/Providers';
import store from '~/store';
import { checkIfScrollable, cn, removeFocusRings } from '~/utils';
import { ChatToolDown } from './ChatFormTools';
import CollapseChat from './CollapseChat';
import FileFormWrapper from './Files/FileFormWrapper';
import SendButton from './SendButton';
import StopButton from './StopButton';

const ChatForm = ({ isLingsi, setShowCode, index = 0 }) => {
  const submitButtonRef = useRef<HTMLButtonElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null);
  useQueryParams({ textAreaRef });

  const localize = useLocalize();

  const [isOutMaxToken, setIsOutMaxToken] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isScrollable, setIsScrollable] = useState(false);


  const maximizeChatSpace = useRecoilValue(store.maximizeChatSpace);
  const [searchType, setSearchType] = useRecoilState(store.searchType);
  const [isSearch, setIsSearch] = useRecoilState(store.isSearch);
  const [chatModel, setChatModel] = useRecoilState(store.chatModel);

  const isSearching = useRecoilValue(store.isSearching);
  const [showStopButton, setShowStopButton] = useRecoilState(store.showStopButtonByIndex(index));
  const [showPlusPopover, setShowPlusPopover] = useRecoilState(store.showPlusPopoverFamily(index));
  const [showMentionPopover, setShowMentionPopover] = useRecoilState(
    store.showMentionPopoverFamily(index),
  );

  const chatDirection = useRecoilValue(store.chatDirection).toLowerCase();
  const isRTL = chatDirection === 'rtl';

  const { requiresKey } = useRequiresKey();
  const handleKeyUp = useHandleKeyUp({
    index,
    textAreaRef,
    setShowPlusPopover,
    setShowMentionPopover,
  });

  const { data: bsConfig } = useGetBsConfig()
  const { handlePaste, handleKeyDown, handleCompositionStart, handleCompositionEnd } = useTextarea({
    textAreaRef,
    submitButtonRef,
    setIsScrollable,
    disabled: !!(requiresKey ?? false),
    placeholder: isLingsi ? (bsConfig?.linsightConfig?.input_placeholder || '请输入你的任务目标，然后交给 BISHENG 灵思') : bsConfig?.inputPlaceholder
  });

  const {
    files,
    setFiles,
    conversation,
    isSubmitting,
    filesLoading,
    newConversation,
    handleStopGenerating,
  } = useChatContext();
  const methods = useChatFormContext();
  const {
    addedIndex,
    generateConversation,
    conversation: addedConvo,
    setConversation: setAddedConvo,
    isSubmitting: isSubmittingAdded,
  } = useAddedChatContext();
  const showStopAdded = useRecoilValue(store.showStopButtonByIndex(addedIndex));

  const { clearDraft } = useAutoSave({
    conversationId: useMemo(() => conversation?.conversationId, [conversation]),
    textAreaRef,
    files,
    setFiles,
  });

  const navigator = useNavigate()

  const assistantMap = useAssistantsMapContext();
  const { submitMessage, submitPrompt } = useSubmitMessage({ clearDraft });

  const { endpoint: _endpoint, endpointType } = conversation ?? { endpoint: null };
  const endpoint = endpointType ?? _endpoint;

  const { data: fileConfig = defaultFileConfig } = useGetFileConfig({
    select: (data) => mergeFileConfig(data),
  });

  const endpointFileConfig = fileConfig.endpoints[endpoint ?? ''];
  const invalidAssistant = useMemo(
    () =>
      isAssistantsEndpoint(conversation?.endpoint) &&
      (!(conversation?.assistant_id ?? '') ||
        !assistantMap?.[conversation?.endpoint ?? ''][conversation?.assistant_id ?? '']),
    [conversation?.assistant_id, conversation?.endpoint, assistantMap],
  );
  const disableInputs = useMemo(
    () => !!((requiresKey ?? false) || invalidAssistant),
    [requiresKey, invalidAssistant],
  );

  const { ref, ...registerProps } = methods.register('text', {
    required: true,
    onChange: (e) => {
      methods.setValue('text', e.target.value, { shouldValidate: true });
    },
  });

  useEffect(() => {
    if (!isSearching && textAreaRef.current && !disableInputs) {
      textAreaRef.current.focus();
    }
  }, [isSearching, disableInputs]);

  useEffect(() => {
    if (textAreaRef.current) {
      checkIfScrollable(textAreaRef.current);
    }
  }, []);

  useEffect(() => {
    if (files.size >= 1) {
      setIsSearch(false);
    }
    let total = 0;
    files.forEach((item: any) => {
      total = item?.token + total;
    });
    const isOut = total > 300000;
    setIsOutMaxToken(isOut);
  }, [files]);

  useEffect(() => {
    searchType ? setIsSearch(true) : setIsSearch(false);
  }, [searchType]);

  const endpointSupportsFiles: boolean = supportsFiles[endpointType ?? endpoint ?? ''] ?? false;
  const isUploadDisabled: boolean = endpointFileConfig?.disabled ?? false;

  const baseClasses = cn(
    'md:py-3.5 m-0 w-full resize-none py-[13px] bg-surface-tertiary placeholder-black/50 dark:placeholder-white/50 [&:has(textarea:focus)]:shadow-[0_2px_6px_rgba(0,0,0,.5)]',
    isCollapsed ? 'max-h-[52px]' : 'max-h-96',
    isLingsi && 'bg-transparent'
  );

  const uploadActive = endpointSupportsFiles && !isUploadDisabled;
  const speechClass = isRTL
    ? `pr-${uploadActive ? '6' : '4'} pl-6`
    : `pl-${uploadActive ? '6' : '4'} pr-6`;

  // linsight工具
  const [tools, setTools] = useState([])
  // 获取剩余次数
  const { data: count, refetch } = useGetUserLinsightCountQuery()
  useEffect(() => {
    bsConfig?.linsight_invitation_code && refetch()
  }, [bsConfig?.linsight_invitation_code])

  const accept = useMemo(() => {
    if (isLingsi) {
      return bsConfig?.enable_etl4lm
        ? '.pdf,.txt,.docx,.ppt,.pptx,.md,.html,.xls,.xlsx,.doc,.png,.jpg,.jpeg,.bmp'
        : '.pdf,.txt,.docx,.doc,.ppt,.pptx,.md,.html,.xls,.xlsx'
    }
    return ''
  }, [isLingsi])

  return (
    <form
      onSubmit={methods.handleSubmit((data) => {
        console.log('bsConfig?.linsight_invitation_code :>> ', bsConfig?.linsight_invitation_code, isLingsi, count);
        if (bsConfig?.linsight_invitation_code && isLingsi && count === 0) return setShowCode(true)
        submitMessage({ ...data, linsight: isLingsi, tools })
        isLingsi && navigator('/linsight/new')
      })}
      className={cn(
        'mx-auto flex flex-row gap-3 pl-2 transition-all duration-200 last:mb-2',
        maximizeChatSpace ? 'w-full max-w-full' : 'md:max-w-2xl xl:max-w-3xl',
      )}
    >
      <div className="relative flex h-full flex-1 items-stretch md:flex-col">
        {/* 切换模型 */}
        {/* {showPlusPopover && !isAssistantsEndpoint(endpoint) && (
          <Mention
            setShowMentionPopover={setShowPlusPopover}
            newConversation={generateConversation}
            textAreaRef={textAreaRef}
            commandChar="+"
            placeholder="com_ui_add_model_preset"
            includeAssistants={false}
          />
        )}
        {showMentionPopover && (
          <Mention
            setShowMentionPopover={setShowMentionPopover}
            newConversation={newConversation}
            textAreaRef={textAreaRef}
          />
        )} */}
        {/* 快捷提示词选择 */}
        {/* <PromptsCommand index={index} textAreaRef={textAreaRef} submitPrompt={submitPrompt} /> */}
        <div className={cn("transitional-all relative flex w-full flex-grow flex-col overflow-hidden rounded-3xl bg-surface-tertiary pb-8 z-10 text-text-primary duration-200 border border-transparent",
          isLingsi && 'border-blue-400 bg-gradient-to-b from-[#F2F5FF] to-white'
        )}>
          {/* 临时对话 */}
          {/* <TemporaryChat
            isTemporaryChat={isTemporaryChat}
            setIsTemporaryChat={setIsTemporaryChat}
          /> */}
          {/* 操作已添加的对话 */}
          {/* <TextareaHeader addedConvo={addedConvo} setAddedConvo={setAddedConvo} /> */}
          {/* {bsConfig?.fileUpload.enabled && */}
          <FileFormWrapper
            accept={accept}
            fileTip={!isLingsi}
            noUpload={!bsConfig?.fileUpload.enabled}
            disableInputs={disableInputs}
            disabledSearch={isSearch && !isLingsi}
          >
            {endpoint && (
              <>
                <CollapseChat
                  isCollapsed={isCollapsed}
                  isScrollable={isScrollable}
                  setIsCollapsed={setIsCollapsed}
                />
                <TextareaAutosize
                  {...registerProps}
                  ref={(e) => {
                    ref(e);
                    textAreaRef.current = e;
                  }}
                  disabled={disableInputs}
                  onPaste={handlePaste}
                  onKeyDown={handleKeyDown}
                  onKeyUp={handleKeyUp}
                  onHeightChange={() => {
                    if (textAreaRef.current) {
                      const scrollable = checkIfScrollable(textAreaRef.current);
                      setIsScrollable(scrollable);
                    }
                  }}
                  onCompositionStart={handleCompositionStart}
                  onCompositionEnd={handleCompositionEnd}
                  tabIndex={0}
                  data-testid="text-input"
                  rows={2}
                  onFocus={() => isCollapsed && setIsCollapsed(false)}
                  onClick={() => isCollapsed && setIsCollapsed(false)}
                  style={{ height: isLingsi ? 124 : 84, overflowY: 'auto' }}
                  className={cn(
                    baseClasses,
                    speechClass,
                    removeFocusRings,
                    'transition-[max-height] duration-200',
                    'transition-[height] duration-500',
                    isLingsi ? 'min-h-32' : 'min-h-24'
                  )}
                />
              </>
            )}
          </FileFormWrapper>
          {/* 发送和停止 */}
          <div className="absolute bottom-2 right-3">
            {(isSubmitting || isSubmittingAdded) && (showStopButton || showStopAdded) ? (
              <StopButton stop={handleStopGenerating} setShowStopButton={setShowStopButton} />
            ) : (
              endpoint && (
                <SendButton
                  ref={submitButtonRef}
                  isLingsi={isLingsi}
                  control={methods.control}
                  disabled={!!(filesLoading || isSubmitting || disableInputs || isOutMaxToken)}
                />
              )
            )}
          </div>
          {/* 深度思考 联网 */}
          <div className="absolute bottom-2 left-3 flex gap-2">
            {!isLingsi && <ModelSelect value={chatModel.id} options={bsConfig?.models} onChange={val => {
              setChatModel({ id: Number(val), name: bsConfig?.models?.find(item => item.id === val)?.displayName || '' })
            }} />}
            <ChatToolDown
              tools={tools}
              setTools={setTools}
              linsi={isLingsi}
              config={bsConfig}
              searchType={searchType}
              setSearchType={setSearchType}
              disabled={!!files.size}
            />
          </div>
        </div>
        {/* 气泡 */}
        <div className={cn(
          "absolute w-full rounded-b-[28px] pt-10 -bottom-10 flex justify-between",
          "bg-gradient-to-b from-[#DEE8FF] via-[#DEE8FF] to-[rgba(222,232,255,0.4)]",
          "backdrop-blur-sm", // 添加毛玻璃效果
          "transition-[opacity,transform] duration-500 ease-[cubic-bezier(0.4,0,0.2,1)]",
          "border border-opacity-10 border-[#143BFF]", // 添加边框和阴影
          isLingsi ? "opacity-100" : "opacity-0 pointer-events-none",
          isLingsi ? "translate-y-0" : "translate-y-2" // 整体轻微上浮
        )}>
          <p className={cn(
            "py-2.5 px-6 text-sm text-[#6C7EC5] flex items-center",
            "transition-all duration-300 ease-out delay-200",
            "rounded-full mx-4", // 文字背景
            isLingsi ? "translate-y-0 opacity-100" : "-translate-y-3 opacity-0"
          )}>
            <span className="font-semibold text-[#4A5AA1] mr-2"><Spline size={14} /></span>
            大模型结合业务指导手册自主规划并完成复杂任务
          </p>
          {bsConfig?.linsight_invitation_code &&
            <div className='flex gap-4 items-center pr-6'>
              <span className='text-xs text-gray-500'>剩余任务次数： {count}次</span>
              {!count && <Button size="sm" className='h-6 text-xs' onClick={() => setShowCode(true)}>去激活</Button>}
            </div>
          }
        </div>
      </div>
    </form>
  );
};

const ModelSelect = ({ options, value, onChange }: { options?: BsConfig['models'], value: number, onChange: (value: string) => void }) => {

  const label = useMemo(() => {
    if (!options) return ''
    // 默认选中第一个
    if (!value) onChange(options[0].id + '')
    const currentOpt = options.find(opt => Number(opt.id) === value)
    if (currentOpt) {
      return currentOpt.displayName
    } else {
      options[0] && onChange(options[0].id + '')
      return ''
    }
  }, [options, value])

  return <Select onValueChange={onChange}>
    <SelectTrigger className="h-7 rounded-full px-2 bg-white dark:bg-transparent">
      <div
        className='flex gap-2'
      >
        <Rotate3DIcon size="16" />
        <span className="text-xs font-normal">{label}</span>
      </div>
    </SelectTrigger>
    <SelectContent className='bg-white'>
      {options?.map((opt) => <SelectItem key={opt.key} value={opt.id + ''}>{opt.displayName}</SelectItem>)}
    </SelectContent>
  </Select>
}



export default memo(ChatForm);

