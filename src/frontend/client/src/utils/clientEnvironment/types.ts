export type ClientChannel = "web" | "desktop";
export type DeviceType = "phone" | "tablet" | "desktop" | "unknown";
export type ClientOS =
  "windows" | "macos" | "android" | "ios" | "linux" | "unknown";
export type IdentitySource =
  | "host"
  | "legacy-bridge"
  | "entry"
  | "session"
  | "client-hints"
  | "user-agent"
  | "default"
  | "unknown";

export type DesktopHostInfo = Readonly<{
  protocolVersion: 1;
  channel: "desktop";
  deviceType: "desktop";
  os: "windows" | "macos" | "linux" | "unknown";
}>;

export type DesktopPresentation = Readonly<{
  hostInfo?: unknown;
  reportLanding?: (landing: boolean) => void;
  reportKnowledgeDialog?: (open: boolean) => void;
  reportNavigation?: (navigation: unknown) => void;
  onProjectsChanged?: (listener: () => void) => (() => void);
  reportSettings?: (section: string) => void;
  requestSettingsClose?: () => void;
  requestSettingsFocus?: (direction: "previous" | "next") => void;
}>;

export type ClientEnvironment = Readonly<{
  channel: ClientChannel;
  deviceType: DeviceType;
  os: ClientOS;
  sources: Readonly<{
    channel: IdentitySource;
    deviceType: IdentitySource;
    os: IdentitySource;
  }>;
  capabilities: Readonly<{
    hasNativePresentation: boolean;
    /** embed=mobile-app opts into a native host owning the entire chat header. */
    hasHostChatHeader: boolean;
  }>;
}>;

declare global {
  interface Window {
    dshChatPresentation?: DesktopPresentation;
  }
}
