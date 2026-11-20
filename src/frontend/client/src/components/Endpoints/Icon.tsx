import { UserAvatar } from '@bisheng/ui';
import type { IconProps } from '~/common';
import MessageEndpointIcon from './MessageEndpointIcon';

interface EndpointIconProps extends IconProps {
  name?: string | null;
  userAvatar?: string | null;
}

export function Icon({ name, userAvatar, ...props }: EndpointIconProps) {
  if (!props.isCreatedByUser) return <MessageEndpointIcon {...props} />;

  const { size = 30, className } = props;
  return (
    <div className={className} style={{ width: size, height: size }}>
      <UserAvatar className="size-full" fallbackClassName="text-caption" name={name} src={userAvatar} />
    </div>
  );
}

export default Icon;
