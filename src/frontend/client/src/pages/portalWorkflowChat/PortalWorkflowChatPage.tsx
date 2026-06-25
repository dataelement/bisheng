import StandaloneChatPage from '~/pages/standaloneChat/StandaloneChatPage';

export default function PortalWorkflowChatPage() {
  return (
    <StandaloneChatPage
      mode="auth"
      flowType="workflow"
      hideSidebar
      forceNewChatOnLoad
    />
  );
}
