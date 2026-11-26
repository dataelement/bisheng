import * as React from "react"
import { Filled } from "bisheng-icons"
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

    // Read one Unicode code point, preserving supplementary CJK characters.
    // Without a name (e.g. a guest-link visitor) show a generic person icon
    // instead of a "?" glyph.
    const initial = Array.from((name || "").trim())[0]?.toUpperCase();

    // 默认灰底白字，与频道/知识空间成员管理列表一致（避免与 bg-primary 蓝色兜底混用）
    return (
      <div
        ref={ref}
        className={cn(
          "flex h-full w-full items-center justify-center aspect-square rounded-full bg-fill-4 text-white font-medium tracking-tight",
          className
        )}
        {...props}
      >
        {initial ?? <Filled.Person className="h-3/5 w-3/5" aria-hidden />}
      </div>
    );
  }
);

AvatarName.displayName = "AvatarName";

export { Avatar, AvatarImage, AvatarName }
