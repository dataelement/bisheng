import { FileText, GlobeIcon, Rotate3DIcon } from 'lucide-react';
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useRecoilState, useRecoilValue } from 'recoil';
import { Button, TextareaAutosize } from '~/components/ui';
import { Select, SelectContent, SelectItem, SelectTrigger } from '~/components/ui/Select';
import { useGetBsConfig, useGetFileConfig } from '~/data-provider';
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
import CollapseChat from './CollapseChat';
import FileFormWrapper from './Files/FileFormWrapper';
import SendButton from './SendButton';
import StopButton from './StopButton';

const ChatForm = ({ index = 0 }) => {
  const submitButtonRef = useRef<HTMLButtonElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null);
  useQueryParams({ textAreaRef });

  const localize = useLocalize();

  const [isOutMaxToken, setIsOutMaxToken] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isScrollable, setIsScrollable] = useState(false);

  const SpeechToText = useRecoilValue(store.speechToText);
  const TextToSpeech = useRecoilValue(store.textToSpeech);
  const automaticPlayback = useRecoilValue(store.automaticPlayback);
  const maximizeChatSpace = useRecoilValue(store.maximizeChatSpace);
  const [isTemporaryChat, setIsTemporaryChat] = useRecoilState<boolean>(store.isTemporary);

  const [modelType, setModelType] = useRecoilState(store.modelType);
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
    placeholder: bsConfig?.inputPlaceholder
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
    isCollapsed ? 'max-h-[52px]' : 'max-h-[65vh] md:max-h-[75vh]',
  );

  const uploadActive = endpointSupportsFiles && !isUploadDisabled;
  const speechClass = isRTL
    ? `pr-${uploadActive ? '6' : '4'} pl-6`
    : `pl-${uploadActive ? '6' : '4'} pr-6`;

  return (
    <form
      onSubmit={methods.handleSubmit((data) => submitMessage(data))}
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
        <div className="transitional-all relative flex w-full flex-grow flex-col overflow-hidden rounded-3xl bg-surface-tertiary pb-8 text-text-primary duration-200">
          {/* 临时对话 */}
          {/* <TemporaryChat
            isTemporaryChat={isTemporaryChat}
            setIsTemporaryChat={setIsTemporaryChat}
          /> */}
          {/* 操作已添加的对话 */}
          {/* <TextareaHeader addedConvo={addedConvo} setAddedConvo={setAddedConvo} /> */}
          {/* {bsConfig?.fileUpload.enabled && */}
          <FileFormWrapper noUpload={!bsConfig?.fileUpload.enabled} disableInputs={disableInputs} disabledSearch={isSearch}>
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
                  style={{ height: 44, overflowY: 'auto' }}
                  className={cn(
                    baseClasses,
                    speechClass,
                    removeFocusRings,
                    'transition-[max-height] duration-200',
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
                  control={methods.control}
                  disabled={!!(filesLoading || isSubmitting || disableInputs || isOutMaxToken)}
                />
              )
            )}
          </div>
          {/* 深度思考 联网 */}
          <div className="absolute bottom-2 left-3 flex gap-2">
            <ModelSelect value={chatModel.id} options={bsConfig?.models} onChange={val => {
              setChatModel({ id: Number(val), name: bsConfig?.models?.find(item => item.id === val)?.displayName || '' })
            }} />
            {/* <div className="absolute bottom-2 left-5 flex gap-2">
            <Button
              type="button"
              variant={'outline'}
              className={cn(
                'h-6 rounded-full px-2',
                'deepseek-reasoner' === modelType && buttonActiveStyle,
              )}
              onClick={() => {
                if (modelType === 'deepseek-reasoner') {
                  setModelType('');
                } else {
                  setModelType('deepseek-reasoner');
                }
              }}
            >
              <Rotate3DIcon size="16" />
              <span className="text-xs font-normal">{localize('com_ui_model_think')}</span>
            </Button> */}
            {/* <Button
              type="button"
              variant={'outline'}
              className={cn(
                'h-6 rounded-full px-2',
                'deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B' === modelType && buttonActiveStyle,
              )}
              onClick={() => {
                if (modelType === 'deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B') {
                  setModelType('');
                } else {
                  setModelType('deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B');
                }
              }}
            >
              <Rotate3DIcon size="16" />
              <span className="text-xs font-normal">{localize('com_ui_model_shougang')}</span>
            </Button> */}
            {
              bsConfig?.webSearch.enabled && <Button
                type="button"
                variant={'outline'}
                className={cn(
                  'h-7 rounded-full px-2 dark:bg-transparent dark:border-gray-600',
                  'netSearch' === searchType && buttonActiveStyle,
                )}
                onClick={() => {
                  if (searchType === 'netSearch') {
                    setSearchType('');
                  } else {
                    setSearchType('netSearch');
                  }
                }}
                disabled={!!files.size}
              >
                <GlobeIcon size="16" />
                <span className="text-xs font-normal">{localize('com_ui_model_search')}</span>
              </Button>
            }
            {
              bsConfig?.knowledgeBase.enabled && <Button
                type="button"
                variant={'outline'}
                className={cn(
                  'h-7 rounded-full px-2 dark:bg-transparent dark:border-gray-600',
                  'knowledgeSearch' === searchType && buttonActiveStyle,
                )}
                onClick={() => {
                  if (searchType === 'knowledgeSearch') {
                    setSearchType('');
                  } else {
                    setSearchType('knowledgeSearch');
                  }
                }}
                disabled={!!files.size}
              >
                <FileText size="16" />
                <span className="text-xs font-normal">{localize('com_ui_knowledge_search')}</span>
              </Button>
            }
          </div>
        </div>
      </div>
    </form >
  );
};

const buttonActiveStyle =
  'text-blue-main border-blue-300 bg-blue-100 hover:text-blue-main hover:bg-blue-200';

const ModelSelect = ({ options, value, onChange }: { options?: BsConfig['models'], value: number, onChange: (value: string) => void }) => {

  const label = useMemo(() => {
    if (!options) return ''
    // 默认选中第一个
    if (!value) onChange(options[0].id + '')
    const currentOpt = options.find(opt => Number(opt.id) === value)
    if (currentOpt) {
      return currentOpt.displayName
    } else {
      onChange(options[0].id + '')
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
