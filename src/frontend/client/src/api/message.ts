import request from "./request";

export type MessageTab = "all" | "request";

export interface MessageContentPart {
  type: string;
  content: string;
  metadata?: Record<string, any>;
}

export interface MessageItem {
  id: number;
  content: MessageContentPart[];
  sender: number;
  sender_name: string;
  message_type: string;
  action_code?: string;
  status: string;
  is_read: boolean;
  operator_user_id?: number | null;
  create_time: string;
  update_time: string;
}

export interface MessageListResponse {
  data: MessageItem[];
  total: number;
}

export async function getMessageListApi(params?: {
  tab?: MessageTab;
  only_unread?: boolean;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<MessageListResponse> {
  const resp: any = await request.get(`/api/v1/message/list`, { params });
  // 兼容两种返回结构：
  // 1) axios 风格: { data: { data: [...], total: 9 } }
  // 2) 直接返回:   { data: [...], total: 9 }
  const root = resp?.data ?? resp ?? {};
  const payload = root?.data ?? root ?? {};
  const list = Array.isArray(payload?.data)
    ? payload.data
    : (Array.isArray(payload) ? payload : []);
  return {
    data: list,
    total: payload?.total ?? root?.total ?? list.length ?? 0,
  };
}

export async function getMessageUnreadCountApi(): Promise<{
  total: number;
  notify: number;
  approve: number;
}> {
  const resp: any = await request.get(`/api/v1/message/unread_count`);
  const root = resp?.data ?? resp ?? {};
  const payload = root?.data ?? {};
  return {
    total: payload?.total ?? 0,
    notify: payload?.notify ?? 0,
    approve: payload?.approve ?? 0,
  };
}

export async function markMessageReadApi(message_ids: number[]): Promise<any> {
  return await request.post(`/api/v1/message/mark_read`, { message_ids });
}

export async function markAllMessageReadApi(): Promise<{ marked_count: number }> {
  const resp: any = await request.post(`/api/v1/message/mark_all_read`);
  const root = resp?.data ?? resp ?? {};
  const payload = root?.data ?? {};
  return { marked_count: payload?.marked_count ?? 0 };
}

export async function approveMessageApi(body: { message_id: number; action: "agree" | "reject" }): Promise<any> {
  return await request.post(`/api/v1/message/approve`, body);
}

export async function deleteMessageApi(message_id: number): Promise<boolean> {
  const resp: any = await request.delete(`/api/v1/message/${message_id}`);
  const root = resp?.data ?? resp ?? {};
  return Boolean(root?.data ?? root);
}

