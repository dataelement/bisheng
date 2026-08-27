/** @jest-environment node */

import {
  buildWorkflowInitMessage,
  claimWorkflowHandshake,
  createWorkflowActivation,
  decideWorkflowCloseAction,
  syncWorkflowActivation,
} from './workflowAutoRerun';

const finishedClose = {
  category: 'processing',
  type: 'close',
  chat_id: 'chat-a',
  message: { event: 'workflow_status_checked', status: 'finished' },
};

describe('workflow auto rerun on conversation activation', () => {
  it('auto reruns only a finished historical standalone workflow when enabled', () => {
    const activation = createWorkflowActivation('chat-a');

    expect(decideWorkflowCloseAction({
      data: finishedClose,
      activation,
      enabled: true,
      isStandaloneWorkflow: true,
      isNewConversation: false,
    })).toBe('auto');
  });

  it.each([
    ['disabled', { enabled: false }],
    ['non-standalone', { isStandaloneWorkflow: false }],
    ['new conversation', { isNewConversation: true }],
  ])('falls back to manual rerun when %s', (_name, overrides) => {
    expect(decideWorkflowCloseAction({
      data: finishedClose,
      activation: createWorkflowActivation('chat-a'),
      enabled: true,
      isStandaloneWorkflow: true,
      isNewConversation: false,
      ...overrides,
    })).toBe('manual');
  });

  it('never auto reruns an ordinary runtime close', () => {
    expect(decideWorkflowCloseAction({
      data: { ...finishedClose, message: '' },
      activation: createWorkflowActivation('chat-a'),
      enabled: true,
      isStandaloneWorkflow: true,
      isNewConversation: false,
    })).toBe('manual');
  });

  it('ignores late or already-consumed finished markers', () => {
    expect(decideWorkflowCloseAction({
      data: { ...finishedClose, chat_id: 'chat-b' },
      activation: createWorkflowActivation('chat-a'),
      enabled: true,
      isStandaloneWorkflow: true,
      isNewConversation: false,
    })).toBe('ignore');

    expect(decideWorkflowCloseAction({
      data: finishedClose,
      activation: { chatId: 'chat-a', handled: true, handshakeSent: true },
      enabled: true,
      isStandaloneWorkflow: true,
      isNewConversation: false,
    })).toBe('ignore');
  });

  it('allows a new activation after switching away and back', () => {
    let activation = createWorkflowActivation('chat-a');
    expect(claimWorkflowHandshake(activation, 'chat-a')).toBe(true);
    expect(claimWorkflowHandshake(activation, 'chat-a')).toBe(false);
    activation.handled = true;

    activation = syncWorkflowActivation(activation, 'chat-b');
    expect(activation).toEqual({ chatId: 'chat-b', handled: false, handshakeSent: false });

    activation.handled = true;
    activation = syncWorkflowActivation(activation, 'chat-a');
    expect(activation).toEqual({ chatId: 'chat-a', handled: false, handshakeSent: false });
    expect(claimWorkflowHandshake(activation, 'chat-a')).toBe(true);
  });

  it('builds the same init_data payload used by manual and automatic reruns', () => {
    expect(buildWorkflowInitMessage({
      id: 'flow-1',
      name: 'flow',
      data: { edges: ['edge'], nodes: ['node'], viewport: { x: 0 } },
    }, 'chat-a')).toEqual({
      action: 'init_data',
      chat_id: 'chat-a',
      flow_id: 'flow-1',
      data: {
        id: 'flow-1',
        name: 'flow',
        edges: ['edge'],
        nodes: ['node'],
        viewport: { x: 0 },
      },
    });
  });
});
