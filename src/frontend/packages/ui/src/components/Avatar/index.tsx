import { forwardRef, useState } from 'react';
import type { HTMLAttributes, ImgHTMLAttributes } from 'react';
import cn from '../../utils/cn';

export const Avatar = forwardRef<HTMLSpanElement, HTMLAttributes<HTMLSpanElement>>(
  ({ className, ...props }, ref) => (
    <span
      ref={ref}
      className={cn('relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full', className)}
      {...props}
    />
  ),
);
Avatar.displayName = 'Avatar';

export const AvatarImage = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
  ({ className, ...props }, ref) => (
    <img ref={ref} className={cn('aspect-square h-full w-full', className)} {...props} />
  ),
);
AvatarImage.displayName = 'AvatarImage';

interface AvatarNameProps extends HTMLAttributes<HTMLDivElement> {
  name?: string | null;
}

export const AvatarName = forwardRef<HTMLDivElement, AvatarNameProps>(
  ({ className, name, ...props }, ref) => {
    const [initial = '?'] = Array.from(name?.trim() ?? '');

    return (
      <div
        ref={ref}
        className={cn(
          'flex h-full w-full items-center justify-center aspect-square rounded-full bg-fill-4 text-white font-medium tracking-tight',
          className,
        )}
        {...props}
      >
        {initial.toUpperCase()}
      </div>
    );
  },
);
AvatarName.displayName = 'AvatarName';

export interface UserAvatarProps {
  name?: string | null;
  src?: string | null;
  className?: string;
  fallbackClassName?: string;
  alt?: string;
}

function UserAvatarContent({ src, name, fallbackClassName, alt = '' }: UserAvatarProps) {
  const [failed, setFailed] = useState(false);

  return src && !failed ? (
    <AvatarImage src={src} alt={alt} className="object-cover" onError={() => setFailed(true)} />
  ) : (
    <AvatarName name={name} className={fallbackClassName} aria-hidden="true" />
  );
}

export function UserAvatar({ className, src, ...props }: UserAvatarProps) {
  const source = src?.trim();

  return (
    <Avatar className={className}>
      <UserAvatarContent key={source} src={source} {...props} />
    </Avatar>
  );
}
