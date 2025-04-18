import type { AxiosResponse } from 'axios';
import * as endpoints from './api-endpoints';
import * as config from './config';
import request from './request';
import * as r from './roles';
import * as s from './schemas';
import type * as t from './types';
import * as a from './types/assistants';
import * as f from './types/files';
import * as m from './types/mutations';
import * as q from './types/queries';

export function abortRequestWithMessage(
  endpoint: string,
  abortKey: string,
  message: string,
): Promise<void> {
  return request.post(endpoints.abortRequest(endpoint), { arg: { abortKey, message } });
}

export function revokeUserKey(name: string): Promise<unknown> {
  return request.delete(endpoints.revokeUserKey(name));
}

export function revokeAllUserKeys(): Promise<unknown> {
  return request.delete(endpoints.revokeAllUserKeys());
}

export function deleteUser(): Promise<s.TPreset> {
  return request.delete(endpoints.deleteUser());
}

export function getMessagesByConvoId(conversationId: string): Promise<s.TMessage[]> {
  if (conversationId === 'new') {
    return Promise.resolve([]);
  }
  return request.get(endpoints.messages(conversationId)).then(res => res.data);
}

export function getSharedMessages(shareId: string): Promise<t.TSharedMessagesResponse> {
  return request.get(endpoints.shareMessages(shareId));
}

export const listSharedLinks = async (
  params: q.SharedLinksListParams,
): Promise<q.SharedLinksResponse> => {
  const { pageSize, isPublic, sortBy, sortDirection, search, cursor } = params;

  return request.get(
    endpoints.getSharedLinks(pageSize, isPublic, sortBy, sortDirection, search, cursor),
  );
};

export function getSharedLink(conversationId: string): Promise<t.TSharedLinkGetResponse> {
  return request.get(endpoints.getSharedLink(conversationId));
}

export function createSharedLink(conversationId: string): Promise<t.TSharedLinkResponse> {
  return request.post(endpoints.createSharedLink(conversationId));
}

export function updateSharedLink(shareId: string): Promise<t.TSharedLinkResponse> {
  return request.patch(endpoints.updateSharedLink(shareId));
}

export function deleteSharedLink(shareId: string): Promise<m.TDeleteSharedLinkResponse> {
  return request.delete(endpoints.shareMessages(shareId));
}

export function updateMessage(payload: t.TUpdateMessageRequest): Promise<unknown> {
  const { conversationId, messageId, text } = payload;
  if (!conversationId) {
    throw new Error('conversationId is required');
  }

  return request.put(endpoints.messages(conversationId, messageId), { text });
}

export const editArtifact = async ({
  messageId,
  ...params
}: m.TEditArtifactRequest): Promise<m.TEditArtifactResponse> => {
  return request.post(`/api/messages/artifact/${messageId}`, params);
};

export function updateMessageContent(payload: t.TUpdateMessageContent): Promise<unknown> {
  const { conversationId, messageId, index, text } = payload;
  if (!conversationId) {
    throw new Error('conversationId is required');
  }

  return request.put(endpoints.messages(conversationId, messageId), { text, index });
}

export function updateUserKey(payload: t.TUpdateUserKeyRequest) {
  const { value } = payload;
  if (!value) {
    throw new Error('value is required');
  }

  return request.put(endpoints.keys(), payload);
}

export function getPresets(): Promise<s.TPreset[]> {
  return request.get(endpoints.presets());
}

export function createPreset(payload: s.TPreset): Promise<s.TPreset> {
  return request.post(endpoints.presets(), payload);
}

export function updatePreset(payload: s.TPreset): Promise<s.TPreset> {
  return request.post(endpoints.presets(), payload);
}

export function deletePreset(arg: s.TPreset | undefined): Promise<m.PresetDeleteResponse> {
  return request.post(endpoints.deletePreset(), arg);
}

export function getSearchEnabled(): Promise<boolean> {
  return Promise.resolve(true);
  return request.get(endpoints.searchEnabled());
}

export function getUser(): Promise<t.TUser> {
  return request.get(endpoints.user()).then(res => {
    const { user_id, user_name, create_time, update_time } = res.data;
    return {
      "_id": user_id,
      "name": user_name,
      "username": user_name,
      "email": user_name,
      "emailVerified": true,
      "avatar": null,
      "provider": "local",
      "role": "USER",
      "plugins": [],
      "termsAccepted": false,
      "backupCodes": [],
      "refreshToken": [],
      "createdAt": create_time,
      "updatedAt": update_time,
      "id": user_id
    }
  });
}

export function getUserBalance(): Promise<string> {
  return Promise.resolve('');
  return request.get(endpoints.balance());
}

export const updateTokenCount = (text: string) => {
  return request.post(endpoints.tokenizer(), { arg: text });
};

export const login = (payload: t.TLoginUser): Promise<t.TLoginResponse> => {
  return request.post(endpoints.login(), payload);
};

export const logout = (): Promise<m.TLogoutResponse> => {
  return request.post(endpoints.logout());
};

export const register = (payload: t.TRegisterUser) => {
  return request.post(endpoints.register(), payload);
};

export const userKeyQuery = (name: string): Promise<t.TCheckUserKeyResponse> =>
  Promise.resolve({
    expiresAt: null
  });
// request.get(endpoints.userKeyQuery(name));

export const getLoginGoogle = () => {
  return request.get(endpoints.loginGoogle());
};

export const requestPasswordReset = (
  payload: t.TRequestPasswordReset,
): Promise<t.TRequestPasswordResetResponse> => {
  return request.post(endpoints.requestPasswordReset(), payload);
};

export const resetPassword = (payload: t.TResetPassword) => {
  return request.post(endpoints.resetPassword(), payload);
};

export const verifyEmail = (payload: t.TVerifyEmail): Promise<t.VerifyEmailResponse> => {
  return request.post(endpoints.verifyEmail(), payload);
};

export const resendVerificationEmail = (
  payload: t.TResendVerificationEmail,
): Promise<t.VerifyEmailResponse> => {
  return request.post(endpoints.resendVerificationEmail(), payload);
};

export const getAvailablePlugins = (): Promise<s.TPlugin[]> => {
  return request.get(endpoints.plugins());
};

export const updateUserPlugins = (payload: t.TUpdateUserPlugins) => {
  return request.post(endpoints.userPlugins(), payload);
};

/* Config */

export const getStartupConfig = (): Promise<config.TStartupConfig> => {
  // return request.get(endpoints.config());
  return Promise.resolve({
    "appTitle": "LibreChat",
    "socialLogins": [
      "github",
      "google",
      "discord",
      "openid",
      "facebook",
      "apple"
    ],
    "discordLoginEnabled": false,
    "facebookLoginEnabled": false,
    "githubLoginEnabled": false,
    "googleLoginEnabled": false,
    "appleLoginEnabled": false,
    "openidLoginEnabled": false,
    "openidLabel": "Continue with OpenID",
    "openidImageUrl": "",
    "serverDomain": "http://localhost:3080",
    "emailLoginEnabled": true,
    "registrationEnabled": true,
    "socialLoginEnabled": false,
    "emailEnabled": false,
    "passwordResetEnabled": false,
    "checkBalance": false,
    "showBirthdayIcon": false,
    "helpAndFaqURL": "https://librechat.ai",
    "interface": {
      "endpointsMenu": true,
      "modelSelect": true,
      "parameters": true,
      "presets": true,
      "sidePanel": true,
      "privacyPolicy": {
        "externalUrl": "https://librechat.ai/privacy-policy",
        "openNewTab": true
      },
      "termsOfService": {
        "externalUrl": "https://librechat.ai/tos",
        "openNewTab": true,
        "modalAcceptance": true,
        "modalTitle": "Terms of Service for LibreChat",
        "modalContent": "# Terms and Conditions for LibreChat\n\n*Effective Date: February 18, 2024*\n\nWelcome to LibreChat, the informational website for the open-source AI chat platform, available at https://librechat.ai. These Terms of Service (\"Terms\") govern your use of our website and the services we offer. By accessing or using the Website, you agree to be bound by these Terms and our Privacy Policy, accessible at https://librechat.ai//privacy.\n\n## 1. Ownership\n\nUpon purchasing a package from LibreChat, you are granted the right to download and use the code for accessing an admin panel for LibreChat. While you own the downloaded code, you are expressly prohibited from reselling, redistributing, or otherwise transferring the code to third parties without explicit permission from LibreChat.\n\n## 2. User Data\n\nWe collect personal data, such as your name, email address, and payment information, as described in our Privacy Policy. This information is collected to provide and improve our services, process transactions, and communicate with you.\n\n## 3. Non-Personal Data Collection\n\nThe Website uses cookies to enhance user experience, analyze site usage, and facilitate certain functionalities. By using the Website, you consent to the use of cookies in accordance with our Privacy Policy.\n\n## 4. Use of the Website\n\nYou agree to use the Website only for lawful purposes and in a manner that does not infringe the rights of, restrict, or inhibit anyone else's use and enjoyment of the Website. Prohibited behavior includes harassing or causing distress or inconvenience to any person, transmitting obscene or offensive content, or disrupting the normal flow of dialogue within the Website.\n\n## 5. Governing Law\n\nThese Terms shall be governed by and construed in accordance with the laws of the United States, without giving effect to any principles of conflicts of law.\n\n## 6. Changes to the Terms\n\nWe reserve the right to modify these Terms at any time. We will notify users of any changes by email. Your continued use of the Website after such changes have been notified will constitute your consent to such changes.\n\n## 7. Contact Information\n\nIf you have any questions about these Terms, please contact us at contact@librechat.ai.\n\nBy using the Website, you acknowledge that you have read these Terms of Service and agree to be bound by them.\n"
      },
      "bookmarks": true,
      "prompts": true,
      "multiConvo": true,
      "agents": true,
      "temporaryChat": true,
      "runCode": true,
      "customWelcome": "Welcome to LibreChat! Enjoy your experience."
    },
    "sharedLinksEnabled": true,
    "publicSharedLinksEnabled": true,
    "instanceProjectId": "67c96484a4e95437007d43eb",
    "ldap": {
      "enabled": false
    }
  })
};

export const getBishengConfig = (): Promise<config.BsConfig> => {
  return request.get(endpoints.bsConfig()).then(res => res.data);
};

export const getAIEndpoints = (): Promise<t.TEndpointsConfig> => {
  // return request.get(endpoints.aiEndpoints());
  return Promise.resolve({
    Deepseek: {
      "order": 9999,
      "type": "custom",
      "userProvide": false,
      "userProvideURL": false,
      "modelDisplayLabel": "Deepseek"
    }
  })
};

export const getModels = async (): Promise<t.TModelsConfig> => {
  return Promise.resolve({
    Deepseek: ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"]
  })
  return request.get(endpoints.models());
};

export const getEndpointsConfigOverride = (): Promise<unknown | boolean> => {
  return request.get(endpoints.endpointsConfigOverride());
};

/* Assistants */

export const createAssistant = ({
  version,
  ...data
}: a.AssistantCreateParams): Promise<a.Assistant> => {
  return request.post(endpoints.assistants({ version }), data);
};

export const getAssistantById = ({
  endpoint,
  assistant_id,
  version,
}: {
  endpoint: s.AssistantsEndpoint;
  assistant_id: string;
  version: number | string | number;
}): Promise<a.Assistant> => {
  return request.get(
    endpoints.assistants({
      path: assistant_id,
      endpoint,
      version,
    }),
  );
};

export const updateAssistant = ({
  assistant_id,
  data,
  version,
}: {
  assistant_id: string;
  data: a.AssistantUpdateParams;
  version: number | string;
}): Promise<a.Assistant> => {
  return request.patch(
    endpoints.assistants({
      path: assistant_id,
      version,
    }),
    data,
  );
};

export const deleteAssistant = ({
  assistant_id,
  model,
  endpoint,
  version,
}: m.DeleteAssistantBody & { version: number | string }): Promise<void> => {
  return request.delete(
    endpoints.assistants({
      path: assistant_id,
      options: { model, endpoint },
      version,
    }),
  );
};

export const listAssistants = (
  params: a.AssistantListParams,
  version: number | string,
): Promise<a.AssistantListResponse> => {
  return request.get(
    endpoints.assistants({
      version,
      options: params,
    }),
  );
};

export function getAssistantDocs({
  endpoint,
  version,
}: {
  endpoint: s.AssistantsEndpoint | string;
  version: number | string;
}): Promise<a.AssistantDocument[]> {
  if (!s.isAssistantsEndpoint(endpoint)) {
    return Promise.resolve([]);
  }
  return request.get(
    endpoints.assistants({
      path: 'documents',
      version,
      options: { endpoint },
      endpoint: endpoint as s.AssistantsEndpoint,
    }),
  );
}

/* Tools */

export const getAvailableTools = (
  _endpoint: s.AssistantsEndpoint | s.EModelEndpoint.agents,
  version?: number | string,
): Promise<s.TPlugin[]> => {
  let path = '';
  if (s.isAssistantsEndpoint(_endpoint)) {
    const endpoint = _endpoint as s.AssistantsEndpoint;
    path = endpoints.assistants({
      path: 'tools',
      endpoint: endpoint,
      version: version ?? config.defaultAssistantsVersion[endpoint],
    });
  } else {
    path = endpoints.agents({
      path: 'tools',
    });
  }

  return request.get(path);
};

export const getVerifyAgentToolAuth = (
  params: q.VerifyToolAuthParams,
): Promise<q.VerifyToolAuthResponse> => {
  return request.get(
    endpoints.agents({
      path: `tools/${params.toolId}/auth`,
    }),
  );
};

export const callTool = <T extends m.ToolId>({
  toolId,
  toolParams,
}: {
  toolId: T;
  toolParams: m.ToolParams<T>;
}): Promise<m.ToolCallResponse> => {
  return request.post(
    endpoints.agents({
      path: `tools/${toolId}/call`,
    }),
    toolParams,
  );
};

export const getToolCalls = (params: q.GetToolCallParams): Promise<q.ToolCallResults> => {
  return Promise.resolve([]);
  return request.get(
    endpoints.agents({
      path: 'tools/calls',
      options: params,
    }),
  );
};

/* Files */

export const getFiles = (): Promise<f.TFile[]> => {
  return Promise.resolve([]);
  return request.get(endpoints.files());
};

export const getFileConfig = (): Promise<f.FileConfig> => {
  return Promise.resolve({});
  return request.get(`${endpoints.files()}/config`);
};

export const uploadImage = (
  data: FormData,
  signal?: AbortSignal | null,
): Promise<f.TFileUpload> => {
  const requestConfig = signal ? { signal } : undefined;
  return request.postMultiPart(endpoints.images(), data, requestConfig).then(res => {
    // res.data.temp_file_id = data.get('file_id')
    return res.data
  });
};

export const uploadFile = (data: FormData, signal?: AbortSignal | null): Promise<f.TFileUpload> => {
  const requestConfig = signal ? { signal } : undefined;
  return request.postMultiPart(endpoints.images(), data, requestConfig).then(res => res.data);
};

/* actions */

export const updateAction = (data: m.UpdateActionVariables): Promise<m.UpdateActionResponse> => {
  const { assistant_id, version, ...body } = data;
  return request.post(
    endpoints.assistants({
      path: `actions/${assistant_id}`,
      version,
    }),
    body,
  );
};

export function getActions(): Promise<a.Action[]> {
  return request.get(
    endpoints.agents({
      path: 'actions',
    }),
  );
}

export const deleteAction = async ({
  assistant_id,
  action_id,
  model,
  version,
  endpoint,
}: m.DeleteActionVariables & { version: number | string }): Promise<void> =>
  request.delete(
    endpoints.assistants({
      path: `actions/${assistant_id}/${action_id}/${model}`,
      version,
      endpoint,
    }),
  );

/**
 * Agents
 */

export const createAgent = ({ ...data }: a.AgentCreateParams): Promise<a.Agent> => {
  return request.post(endpoints.agents({}), data);
};

export const getAgentById = ({ agent_id }: { agent_id: string }): Promise<a.Agent> => {
  return request.get(
    endpoints.agents({
      path: agent_id,
    }),
  );
};

export const updateAgent = ({
  agent_id,
  data,
}: {
  agent_id: string;
  data: a.AgentUpdateParams;
}): Promise<a.Agent> => {
  return request.patch(
    endpoints.agents({
      path: agent_id,
    }),
    data,
  );
};

export const duplicateAgent = ({
  agent_id,
}: m.DuplicateAgentBody): Promise<{ agent: a.Agent; actions: a.Action[] }> => {
  return request.post(
    endpoints.agents({
      path: `${agent_id}/duplicate`,
    }),
  );
};

export const deleteAgent = ({ agent_id }: m.DeleteAgentBody): Promise<void> => {
  return request.delete(
    endpoints.agents({
      path: agent_id,
    }),
  );
};

export const listAgents = (params: a.AgentListParams): Promise<a.AgentListResponse> => {
  return request.get(
    endpoints.agents({
      options: params,
    }),
  );
};

/* Tools */

export const getAvailableAgentTools = (): Promise<s.TPlugin[]> => {
  return request.get(
    endpoints.agents({
      path: 'tools',
    }),
  );
};

/* Actions */

export const updateAgentAction = (
  data: m.UpdateAgentActionVariables,
): Promise<m.UpdateAgentActionResponse> => {
  const { agent_id, ...body } = data;
  return request.post(
    endpoints.agents({
      path: `actions/${agent_id}`,
    }),
    body,
  );
};

export const deleteAgentAction = async ({
  agent_id,
  action_id,
}: m.DeleteAgentActionVariables): Promise<void> =>
  request.delete(
    endpoints.agents({
      path: `actions/${agent_id}/${action_id}`,
    }),
  );

/**
 * Imports a conversations file.
 *
 * @param data - The FormData containing the file to import.
 * @returns A Promise that resolves to the import start response.
 */
export const importConversationsFile = (data: FormData): Promise<t.TImportResponse> => {
  return request.postMultiPart(endpoints.importConversation(), data);
};

export const uploadAvatar = (data: FormData): Promise<f.AvatarUploadResponse> => {
  return request.postMultiPart(endpoints.avatar(), data);
};

export const uploadAssistantAvatar = (data: m.AssistantAvatarVariables): Promise<a.Assistant> => {
  return request.postMultiPart(
    endpoints.assistants({
      isAvatar: true,
      path: `${data.assistant_id}/avatar`,
      options: { model: data.model, endpoint: data.endpoint },
      version: data.version,
    }),
    data.formData,
  );
};

export const uploadAgentAvatar = (data: m.AgentAvatarVariables): Promise<a.Agent> => {
  return request.postMultiPart(
    `${endpoints.images()}/agents/${data.agent_id}/avatar`,
    data.formData,
  );
};

export const getFileDownload = async (userId: string, file_id: string): Promise<AxiosResponse> => {
  return request.getResponse(`${endpoints.files()}/download/${userId}/${file_id}`, {
    responseType: 'blob',
    headers: {
      Accept: 'application/octet-stream',
    },
  });
};

export const getCodeOutputDownload = async (url: string): Promise<AxiosResponse> => {
  return request.getResponse(url, {
    responseType: 'blob',
    headers: {
      Accept: 'application/octet-stream',
    },
  });
};

export const deleteFiles = async (payload: {
  files: f.BatchFile[];
  agent_id?: string;
  assistant_id?: string;
  tool_resource?: a.EToolResources;
}): Promise<f.DeleteFilesResponse> =>
  request.deleteWithOptions(endpoints.files(), {
    data: payload,
  });

/* Speech */

export const speechToText = (data: FormData): Promise<f.SpeechToTextResponse> => {
  return request.postMultiPart(endpoints.speechToText(), data);
};

export const textToSpeech = (data: FormData): Promise<ArrayBuffer> => {
  return request.postTTS(endpoints.textToSpeechManual(), data);
};

export const getVoices = (): Promise<f.VoiceResponse> => {
  return request.get(endpoints.textToSpeechVoices());
};

export const getCustomConfigSpeech = (): Promise<t.TCustomConfigSpeechResponse> => {
  return request.get(endpoints.getCustomConfigSpeech());
};

/* conversations */

export function duplicateConversation(
  payload: t.TDuplicateConvoRequest,
): Promise<t.TDuplicateConvoResponse> {
  return request.post(endpoints.duplicateConversation(), payload);
}

export function forkConversation(payload: t.TForkConvoRequest): Promise<t.TForkConvoResponse> {
  return request.post(endpoints.forkConversation(), payload);
}

export function deleteConversation(payload: t.TDeleteConversationRequest) {
  //todo: this should be a DELETE request
  return request.delete(endpoints.deleteConversation() + payload.conversationId);
}

export function clearAllConversations(): Promise<unknown> {
  return request.post(endpoints.deleteConversation(), { arg: {} });
}

export const listConversations = (
  params?: q.ConversationListParams,
): Promise<q.ConversationListResponse> => {
  // Assuming params has a pageNumber property
  const pageNumber = (params?.pageNumber ?? '1') || '1'; // Default to page 1 if not provided
  const isArchived = params?.isArchived ?? false; // Default to false if not provided
  const tags = params?.tags || []; // Default to an empty array if not provided
  return request.get(endpoints.conversations(pageNumber, isArchived, tags)).then(res => {
    const list = res.data
    return {
      conversations: list.map(conv => ({
        "conversationId": conv.chat_id,
        "createdAt": conv.create_time,
        "endpoint": "",
        "endpointType": "",
        "expiredAt": null,
        "files": [],
        "isArchived": false,
        "messages": [],
        "model": "",
        "resendFiles": true,
        "tags": [],
        "title": conv.flow_name,
        "updatedAt": conv.create_time,
        "user": conv.user_id,
        "__v": 0,
        "_id": conv.chat_id,
      })),
      pageNumber: pageNumber,
      pageSize: 40,
      pages: list.length === 40 ? Number(pageNumber) + 1 : pageNumber // Math.round(total / 40)
    }
  });
};

export const listConversationsByQuery = (
  params?: q.ConversationListParams & { searchQuery?: string },
): Promise<q.ConversationListResponse> => {
  const pageNumber = (params?.pageNumber ?? '1') || '1'; // Default to page 1 if not provided
  const searchQuery = params?.searchQuery ?? ''; // If no search query is provided, default to an empty string
  // Update the endpoint to handle a search query
  if (searchQuery !== '') {
    return request.get(endpoints.search(searchQuery, pageNumber));
  } else {
    return request.get(endpoints.conversations(pageNumber));
  }
};

export const searchConversations = async (
  q: string,
  pageNumber: string,
): Promise<t.TSearchResults> => {
  return request.get(endpoints.search(q, pageNumber));
};

export function getConversations(pageNumber: string): Promise<t.TGetConversationsResponse> {
  return request.get(endpoints.conversations(pageNumber));
}

export function getConversationById(id: string): Promise<s.TConversation> {
  return request.get(endpoints.conversationById(id));
}

export function updateConversation(
  payload: t.TUpdateConversationRequest,
): Promise<t.TUpdateConversationResponse> {
  return request.post(endpoints.updateConversation(), {
    conversationId: payload.conversationId,
    name: payload.title
  });
}

export function archiveConversation(
  payload: t.TArchiveConversationRequest,
): Promise<t.TArchiveConversationResponse> {
  return request.post(endpoints.updateConversation(), { arg: payload });
}

export function genTitle(payload: m.TGenTitleRequest): Promise<m.TGenTitleResponse> {
  return request.post(endpoints.genTitle(), payload).then(res => res.data);
}

export function getPrompt(id: string): Promise<{ prompt: t.TPrompt }> {
  return request.get(endpoints.getPrompt(id));
}

export function getPrompts(filter: t.TPromptsWithFilterRequest): Promise<t.TPrompt[]> {
  return request.get(endpoints.getPromptsWithFilters(filter));
}

export function getAllPromptGroups(): Promise<q.AllPromptGroupsResponse> {
  return request.get(endpoints.getAllPromptGroups());
}

export function getPromptGroups(
  filter: t.TPromptGroupsWithFilterRequest,
): Promise<t.PromptGroupListResponse> {
  return request.get(endpoints.getPromptGroupsWithFilters(filter));
}

export function getPromptGroup(id: string): Promise<t.TPromptGroup> {
  return request.get(endpoints.getPromptGroup(id));
}

export function createPrompt(payload: t.TCreatePrompt): Promise<t.TCreatePromptResponse> {
  return request.post(endpoints.postPrompt(), payload);
}

export function updatePromptGroup(
  variables: t.TUpdatePromptGroupVariables,
): Promise<t.TUpdatePromptGroupResponse> {
  return request.patch(endpoints.updatePromptGroup(variables.id), variables.payload);
}

export function deletePrompt(payload: t.TDeletePromptVariables): Promise<t.TDeletePromptResponse> {
  return request.delete(endpoints.deletePrompt(payload));
}

export function makePromptProduction(id: string): Promise<t.TMakePromptProductionResponse> {
  return request.patch(endpoints.updatePromptTag(id));
}

export function updatePromptLabels(
  variables: t.TUpdatePromptLabelsRequest,
): Promise<t.TUpdatePromptLabelsResponse> {
  return request.patch(endpoints.updatePromptLabels(variables.id), variables.payload);
}

export function deletePromptGroup(id: string): Promise<t.TDeletePromptGroupResponse> {
  return request.delete(endpoints.deletePromptGroup(id));
}

export function getCategories(): Promise<t.TGetCategoriesResponse> {
  return request.get(endpoints.getCategories());
}

export function getRandomPrompts(
  variables: t.TGetRandomPromptsRequest,
): Promise<t.TGetRandomPromptsResponse> {
  return request.get(endpoints.getRandomPrompts(variables.limit, variables.skip));
}

/* Roles */
export function getRole(roleName: string): Promise<r.TRole> {
  if (roleName === 'USER') return Promise.resolve({
    "_id": "67c9645671e602aa6aece753",
    "name": "USER",
    "BOOKMARKS": {
      "USE": true
    },
    "PROMPTS": {
      "SHARED_GLOBAL": false,
      "USE": true,
      "CREATE": true
    },
    "AGENTS": {
      "SHARED_GLOBAL": false,
      "USE": true,
      "CREATE": true
    },
    "MULTI_CONVO": {
      "USE": true
    },
    "TEMPORARY_CHAT": {
      "USE": true
    },
    "RUN_CODE": {
      "USE": true
    },
    "__v": 0
  });
  return request.get(endpoints.getRole(roleName));
}

export function updatePromptPermissions(
  variables: m.UpdatePromptPermVars,
): Promise<m.UpdatePermResponse> {
  return request.put(endpoints.updatePromptPermissions(variables.roleName), variables.updates);
}

export function updateAgentPermissions(
  variables: m.UpdateAgentPermVars,
): Promise<m.UpdatePermResponse> {
  return request.put(endpoints.updateAgentPermissions(variables.roleName), variables.updates);
}

/* Tags */
export function getConversationTags(): Promise<t.TConversationTagsResponse> {
  return request.get(endpoints.conversationTags());
}

export function createConversationTag(
  payload: t.TConversationTagRequest,
): Promise<t.TConversationTagResponse> {
  return request.post(endpoints.conversationTags(), payload);
}

export function updateConversationTag(
  tag: string,
  payload: t.TConversationTagRequest,
): Promise<t.TConversationTagResponse> {
  return request.put(endpoints.conversationTags(tag), payload);
}
export function deleteConversationTag(tag: string): Promise<t.TConversationTagResponse> {
  return request.delete(endpoints.conversationTags(tag));
}

export function addTagToConversation(
  conversationId: string,
  payload: t.TTagConversationRequest,
): Promise<t.TTagConversationResponse> {
  return request.put(endpoints.addTagToConversation(conversationId), payload);
}
export function rebuildConversationTags(): Promise<t.TConversationTagsResponse> {
  return request.post(endpoints.conversationTags('rebuild'));
}

export function healthCheck(): Promise<string> {
  return request.get(endpoints.health());
}

export function getUserTerms(): Promise<t.TUserTermsResponse> {
  return request.get(endpoints.userTerms());
}

export function acceptTerms(): Promise<t.TAcceptTermsResponse> {
  return request.post(endpoints.acceptUserTerms());
}

export function getBanner(): Promise<t.TBannerResponse> {
  return request.get(endpoints.banner());
}

export function enableTwoFactor(): Promise<t.TEnable2FAResponse> {
  return request.get(endpoints.enableTwoFactor());
}

export function verifyTwoFactor(payload: t.TVerify2FARequest): Promise<t.TVerify2FAResponse> {
  return request.post(endpoints.verifyTwoFactor(), payload);
}

export function confirmTwoFactor(payload: t.TVerify2FARequest): Promise<t.TVerify2FAResponse> {
  return request.post(endpoints.confirmTwoFactor(), payload);
}

export function disableTwoFactor(): Promise<t.TDisable2FAResponse> {
  return request.post(endpoints.disableTwoFactor());
}

export function regenerateBackupCodes(): Promise<t.TRegenerateBackupCodesResponse> {
  return request.post(endpoints.regenerateBackupCodes());
}

export function verifyTwoFactorTemp(
  payload: t.TVerify2FATempRequest,
): Promise<t.TVerify2FATempResponse> {
  return request.post(endpoints.verifyTwoFactorTemp(), payload);
}

// 知识库模块
export function knowledgeUpload(data: any): Promise<t.TRegenerateBackupCodesResponse> {
  return request.postMultiPart(endpoints.knowledgeUpload(), data);
}
export function queryKnowledge(payload: t.TVerify2FARequest): Promise<f.TFile[]> {
  return request.get(endpoints.queryKnowledge(), { params: payload });
}
export function deleteKnowledge(id: string): Promise<t.TConversationTagResponse> {
  return request.delete(endpoints.deleteKnowledge(id));
}
export function getFileDownloadApi(name: string): Promise<f.TFile> {
  return request.get('/api/v1/download?object_name=' + name);
}
