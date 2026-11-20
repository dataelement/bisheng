import { useRef, type ReactNode } from 'react';
import AiChatInput from './AiChatInput';
import { ChatWelcomeExamples, type ApplyChatWelcomeExample } from './ChatWelcomeExamples';
import { DailyFeaturedApps } from './DailyFeaturedApps';
import Landing from './Landing';
import type { ChatViewModel } from './ChatView';

interface ChatLandingProps {
  model: ChatViewModel;
  composerConfigNotice: ReactNode;
}

export function ChatLanding({ model, composerConfigNotice }: ChatLandingProps) {
  const {
    t, isNew, shareToken, landingHasSelection, setLandingHasSelection,
    composerIdentity, inviteQuotaBar, historyError, isLoading, isClearing,
    bsConfig, taskRunning, isStreaming, isParsingMedia, canUseTaskMode, taskMode,
    handleToggleTaskMode, chatModel, handleModelChange, handleModelAutoChange,
    handleSend, stopGenerating, inputText, setInputText, selectedOrgKbs,
    knowledgeAccessMessage, setSelectedOrgKbs, searchType, setSearchType,
    attachmentAsk, retireAttachmentAsk,
  } = model;
  const applyExampleRef = useRef<ApplyChatWelcomeExample>(null);
  const taskPlaceholder = (bsConfig as { linsightConfig?: { input_placeholder?: string } } | undefined)
    ?.linsightConfig?.input_placeholder;

  return (
    <div className="dsh-chat-landing" data-bisheng-chat-welcome>
      <div className="dsh-chat-welcome-grid">
        {/* The new hero class keeps older Desktop builds from injecting a second list. */}
        <div className="dsh-chat-welcome-hero">
          <Landing isNew={isNew} hideSubtitle={landingHasSelection} onStarterClick={setInputText} />
          {!shareToken && (
            <div className="w-full">
              {inviteQuotaBar}
              {composerConfigNotice}
              <AiChatInput
                key={composerIdentity}
                composerIdentity={composerIdentity}
                elevated
                disabled={Boolean(historyError) || isLoading || isClearing || !bsConfig?.models?.length}
                sendDisabled={taskRunning}
                isStreaming={isStreaming}
                isParsingMedia={isParsingMedia}
                features={{ taskModeEntry: canUseTaskMode, taskMode: taskMode && canUseTaskMode }}
                onToggleTaskMode={handleToggleTaskMode}
                placeholder={taskMode ? taskPlaceholder || t('com_linsight_input_placeholder') : undefined}
                onScrollToBottom={() => {}}
                modelOptions={bsConfig?.models}
                modelValue={chatModel.id}
                onModelChange={handleModelChange}
                onModelAutoChange={handleModelAutoChange}
                onSend={handleSend}
                onStop={stopGenerating}
                value={inputText}
                onChange={setInputText}
                bsConfig={bsConfig}
                selectedOrgKbs={selectedOrgKbs}
                knowledgeAccessMessage={knowledgeAccessMessage}
                onSelectedOrgKbsChange={setSelectedOrgKbs}
                searchType={searchType}
                onSearchTypeChange={setSearchType}
                onSelectionPresenceChange={setLandingHasSelection}
                attachmentAsk={attachmentAsk}
                onAttachmentAskDone={retireAttachmentAsk}
                welcomeExampleRef={applyExampleRef}
              />
            </div>
          )}
        </div>
        <div className="dsh-chat-welcome-tail">
          {!shareToken && !attachmentAsk && (
            <ChatWelcomeExamples
              key={composerIdentity}
              onSelect={(example) => {
                const applyExample = applyExampleRef.current;
                return applyExample ? applyExample(example) : 'unavailable';
              }}
            />
          )}
          <DailyFeaturedApps t={t} />
        </div>
      </div>
    </div>
  );
}
