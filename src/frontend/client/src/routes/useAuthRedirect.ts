import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthContext } from '~/hooks';

export default function useAuthRedirect() {
  const { user, isAuthenticated } = useAuthContext();
  const navigate = useNavigate();

  // 未登录采用路由跳转，此处禁用
  // useEffect(() => {
  //   const timeout = setTimeout(() => {
  //     if (!isAuthenticated) {
  //       navigate(`/${__APP_ENV__.BISHENG_HOST}`, { replace: true });
  //     }
  //   }, 300);

  //   return () => {
  //     clearTimeout(timeout);
  //   };
  // }, [isAuthenticated, navigate]);

  return {
    user,
    isAuthenticated,
  };
}
