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

    const getInitials = (str?: string) => {
      if (!str) return '';
      const cleanStr = str.trim();

      if (/^[a-zA-Z]/.test(cleanStr)) {
        return cleanStr.slice(0, 2).toUpperCase();
      }

      return cleanStr.slice(0, 1);
    };

    return (
      <div
        ref={ref}
        className={cn("flex h-full w-full items-center justify-center aspect-square bg-primary text-white font-medium", className)}
        {...props}
      >
        {getInitials(name)}
      </div>
    );
  }
);

AvatarName.displayName = "AvatarName";

export { Avatar, AvatarImage, AvatarName }