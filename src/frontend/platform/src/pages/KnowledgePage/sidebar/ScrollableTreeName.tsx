import type { ReactNode } from "react";

interface ScrollableTreeNameProps {
  name: string;
  trailing?: ReactNode;
}

export function ScrollableTreeName({ name, trailing }: ScrollableTreeNameProps) {
  return (
    <span className="relative self-stretch">
      {/* The natural width makes the tree scrollable; only the visible copy is truncated. */}
      <span aria-hidden="true" className="invisible flex h-full items-center gap-2 whitespace-nowrap">
        {name}{trailing}
      </span>
      <span
        data-tree-name
        className="absolute inset-y-0 left-0 flex items-center gap-2 overflow-hidden whitespace-nowrap"
        style={{ maxWidth: "max(0px, calc(var(--tree-name-room, 100cqi) - var(--tree-name-gutter, 1rem)))" }}
      >
        <span className="truncate">{name}</span>{trailing}
      </span>
    </span>
  );
}
