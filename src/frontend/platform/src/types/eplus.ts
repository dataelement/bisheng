export type EPlusConnectionStatus =
  | "DISABLED"
  | "CONNECTING"
  | "AUTHENTICATED"
  | "RETRYING"
  | "TAKEN_OVER"
  | "ERROR";

export interface EPlusBotConfig {
  id: number;
  assistant_id: string;
  bot_id: string;
  connection_url: string;
  credential_version: number;
  scope_version: number;
  enabled: boolean;
  is_deleted: boolean;
  connection_status: EPlusConnectionStatus;
  secret_configured: boolean;
  ca_configured: boolean;
  ca_sha256: string | null;
  media_hosts: string[];
  space_ids: number[];
  insecure_transport: boolean;
}

export interface EPlusBotConfigInput {
  bot_id: string;
  connection_url: string;
  secret?: string;
  ca_pem?: string;
  remove_ca: boolean;
  media_hosts: string[];
  space_ids: number[];
  enabled: boolean;
}

export interface EPlusBindableSpace {
  id: number;
  name: string;
}
