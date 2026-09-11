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
  // request.get already returns response.data in this project.
  // Compatible with variants:
  // 1) { status_code, data: { data: [...], total } }
  // 2) { status_code, data: [...] }
  // 3) { data: { data: [...], total } }
  // 4) { data: [...], total }
  // 5) [...]
  const root = resp ?? {};
  const statusCode = root?.status_code ?? root?.code ?? root?.data?.status_code ?? root?.data?.code;
  if (statusCode && statusCode !== 200) {
    throw new Error(root?.status_message || root?.message || "getMessageListApi failed");
  }

  const payload = root?.data ?? root ?? {};
  const list =
    Array.isArray(payload?.data) ? payload.data :
      Array.isArray(payload?.data?.data) ? payload.data.data :
        Array.isArray(payload?.list) ? payload.list :
          Array.isArray(payload) ? payload : [];

  const total =
    Number(payload?.total ?? payload?.data?.total ?? root?.total ?? list.length ?? 0);
  return {
    data: list,
    total,
  };
}

export async function getMessageUnreadCountApi(): Promise<{
  total: number;
  notify: number;
  approve: number;
}> {
  const resp: any = await request.get(`/api/v1/message/unread_count`);
  // request.get already returns response.data in this project.
  // Compatible with both:
  // 1) { status_code, data: { total, notify, approve } }
  // 2) { total, notify, approve }
  const root = resp ?? {};
  const payload = root?.data ?? root ?? {};
  const notify = Number(payload?.notify ?? payload?.notify_count ?? payload?.notification ?? 0);
  const approve = Number(payload?.approve ?? payload?.approve_count ?? payload?.request ?? 0);
  const total = Number(payload?.total ?? payload?.unread_total ?? (notify + approve));
  return {
    total,
    notify,
    approve,
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

