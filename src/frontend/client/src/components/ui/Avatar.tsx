import * as React from "react"
import cn from "~/utils/cn"

const Avatar = React.forwardRef<
  HTMLSpanElement,
  React.HTMLAttributes<HTMLSpanElement>
>(({ className, ...props }, ref) => (
  <span
    ref={ref}
    className={cn("relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full", className)}
    {...props}
  />
))
Avatar.displayName = "Avatar"

const AvatarImage = React.forwardRef<
  HTMLImageElement,
  React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, ...props }, ref) => (
  <img
    ref={ref}
    className={cn("aspect-square h-full w-full", className)}
    {...props}
  />
))
AvatarImage.displayName = "AvatarImage"

// name avatar component
interface AvatarNameProps extends React.HTMLAttributes<HTMLDivElement> {
  name?: string;
}
const AvatarName = React.forwardRef<HTMLDivElement, AvatarNameProps>(
  ({ className, name, ...props }, ref) => {

    // 与频道/知识空间成员管理一致：仅取首字符（拉丁字母大写）
    const getInitials = (str?: string) => {
      const trimmed = (str || "").trim();
      return (trimmed[0] || "?").toUpperCase();
    };

    // 默认灰底白字，与频道/知识空间成员管理列表一致（避免与 bg-primary 蓝色兜底混用）
    return (
      <div
        ref={ref}
        className={cn(
          "flex h-full w-full items-center justify-center aspect-square rounded-full bg-[#C9CDD4] text-white font-medium tracking-tight",
          className
        )}
        {...props}
      >
        {getInitials(name)}
      </div>
    );
  }
);

AvatarName.displayName = "AvatarName";

export { Avatar, AvatarImage, AvatarName }