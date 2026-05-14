import type { LucideProps } from "lucide-react";
import { SquareArrowOutUpRight } from "lucide-react";

/** 全站统一：方框 + 右上方外链箭头（与「分享」描边按钮一致） */
export const ShareOutlineIcon = ({ className, ...props }: LucideProps) => (
    <SquareArrowOutUpRight className={className} strokeWidth={1.75} {...props} />
);
