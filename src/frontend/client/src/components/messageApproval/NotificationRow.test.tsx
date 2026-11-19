import { render, screen } from "@testing-library/react";
import type { MessageItem } from "~/api/message";
import { NotificationRow } from "./NotificationRow";

jest.mock("~/hooks/useLocalize", () => ({
  __esModule: true,
  default: () => (key: string) => key,
}));

const familyName = String.fromCodePoint(0x20bb7);
const senderName = `${familyName}T`;
const notification: MessageItem = {
  id: 5,
  sender: 7,
  sender_name: senderName,
  message_type: "notify",
  status: "approved",
  is_read: false,
  create_time: "2026-11-19T08:00:00Z",
  update_time: "2026-11-19T08:00:00Z",
  content: [{ type: "user", content: `@${senderName}`, metadata: { avatar: "/old.png" } }],
};

const rowHandlers = {
  onMarkRead: jest.fn(),
  onOpenApprovalCenter: jest.fn(),
  formatTime: () => "08:00",
};

it("uses the sender's current avatar and distinguishes explicit absence from a legacy response", () => {
  const { rerender } = render(<NotificationRow notification={{ ...notification, sender_avatar: "/new.png" }} {...rowHandlers} />);
  expect(screen.getByAltText("")).toHaveAttribute("src", "/new.png");

  rerender(<NotificationRow notification={{ ...notification, sender_avatar: null }} {...rowHandlers} />);
  expect(screen.queryByAltText("")).not.toBeInTheDocument();
  expect(screen.getByText(familyName)).toBeVisible();

  rerender(<NotificationRow notification={notification} {...rowHandlers} />);
  expect(screen.getByAltText("")).toHaveAttribute("src", "/old.png");
  expect(rowHandlers.onMarkRead).not.toHaveBeenCalled();
});

it("treats system notifications and unavailable human senders separately", () => {
  const system = { ...notification, sender: 0, sender_name: null, content: [] };
  const { rerender } = render(<NotificationRow notification={system} {...rowHandlers} />);
  expect(screen.getByText("com_system_notice.title")).toBeVisible();
  expect(screen.queryByText("?")).not.toBeInTheDocument();

  rerender(<NotificationRow notification={{ ...system, sender: 77, sender_avatar: null }} {...rowHandlers} />);
  expect(screen.getByText("?")).toBeVisible();
  expect(screen.queryByText("com_system_notice.title")).not.toBeInTheDocument();
  expect(rowHandlers.onMarkRead).not.toHaveBeenCalled();
});

it("preserves a leading at-sign in the current nickname", () => {
  render(<NotificationRow notification={{ ...notification, sender_name: "@Alice", sender_avatar: null }} {...rowHandlers} />);

  expect(screen.getByText("@")).toBeVisible();
  expect(screen.getByText("@Alice")).toBeVisible();
});
