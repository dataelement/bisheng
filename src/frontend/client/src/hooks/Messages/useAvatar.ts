import { initials } from '@dicebear/collection';
import { createAvatar } from '@dicebear/core';
import { useEffect, useState } from 'react';
import type { TUser } from '~/data-provider/data-provider/src';

const avatarCache: Record<string, string> = {};
const useAvatar = (user: TUser | undefined) => {
  const [avatarUri, setAvatarUri] = useState('');

  useEffect(() => {
    if (!user?.username) {
      setAvatarUri('');
      return;
    }

    // 如果已有头像或缓存，直接使用
    if (user.avatar) {
      setAvatarUri(user.avatar);
      return;
    }

    if (avatarCache[user.username]) {
      setAvatarUri(avatarCache[user.username]);
      return;
    }

    // 生成新头像
    const avatar = createAvatar(initials, {
      seed: user.username,
      fontFamily: ['Verdana'],
      fontSize: 36,
    });

    avatar
      .toDataUri()
      .then((dataUri) => {
        avatarCache[user.username] = dataUri; // 更新缓存
        setAvatarUri(dataUri); // 触发重新渲染
      })
      .catch(console.error);

  }, [user?.username, user?.avatar]); // 依赖项优化

  return avatarUri;
};

export default useAvatar;
