import type { LucideProps } from "lucide-react";
import { Share2 } from "lucide-react";

/** 分享（三点连线）；历史名称沿用，避免各业务 import 大面积改动 */
export const ShareOutlineIcon = ({ className, ...props }: LucideProps) => (
    <Share2 className={className} strokeWidth={1.75} {...props} />
);
