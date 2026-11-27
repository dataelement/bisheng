import {
  useMemo,
  useState,
  useEffect,
  ReactNode,
  useContext,
  useCallback,
  createContext,
} from 'react';
import { useNavigate } from 'react-router-dom';
import { useRecoilState } from 'recoil';
import { setTokenHeader, SystemRoles } from '~/types/chat';
import type * as t from '~/types/chat';
import {
  useGetBsConfig,
  useGetRole,
  useGetUserQuery,
  useLoginUserMutation,
  useLogoutUserMutation,
} from '~/hooks/queries/data-provider';
import { TAuthConfig, TUserContext, TAuthContext, TResError } from '~/common';
import { requestHostAuthRenewal } from '@bisheng/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { platformAuth } from '~/api/request';
import store from '~/store';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';

const AuthContext = createContext<TAuthContext | undefined>(undefined);

const AuthContextProvider = ({
  authConfig,
  children,
}: {
  authConfig?: TAuthConfig;
  children: ReactNode;
}) => {
  const queryClient = useQueryClient();
  const { t: translate } = useTranslation();
  const [hostPending, setHostPending] = useState(false);
  const [startupFailed, setStartupFailed] = useState(false);
  const [user, setUser] = useRecoilState(store.user);
  const [token, setToken] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | undefined>(undefined);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const { data: userRole = null } = useGetRole(SystemRoles.USER, {
    enabled: !!(isAuthenticated && (user?.role ?? '')),
  });
  const { data: adminRole = null } = useGetRole(SystemRoles.ADMIN, {
    enabled: !!(isAuthenticated && user?.role === SystemRoles.ADMIN),
  });
  useEffect(() => {
    setIsAuthenticated(Boolean(user));
  }, [user])

  const navigate = useNavigate();
  const { data: bsConfig } = useGetBsConfig()

  const setUserContext = useCallback(
    (userContext: TUserContext) => {
      const { token, isAuthenticated, user, redirect } = userContext;
      setUser(user);
      setToken(token);
      //@ts-ignore - ok for token to be undefined initially
      setTokenHeader(token);
      setIsAuthenticated(isAuthenticated);
      if (redirect == null) {
        return;
      }
      if (redirect.startsWith('http://') || redirect.startsWith('https://')) {
        // For external links, use window.location
        window.location.href = redirect;
        // Or if you want to open in a new tab:
        // window.open(redirect, '_blank');
      } else {
        navigate(redirect, { replace: true });
      }
    },
    [navigate, setUser],
  );
  const doSetError = useCallback((message?: string) => setError(message), []);

  const loginUser = useLoginUserMutation({
    onSuccess: (data: t.TLoginResponse) => {
      const { user, token, twoFAPending, tempToken } = data;
      if (twoFAPending) {
        // Redirect to the two-factor authentication route.
        navigate(`/login/2fa?tempToken=${tempToken}`, { replace: true });
        return;
      }
      setError(undefined);
      setUserContext({ token, isAuthenticated: true, user });
    },
    onError: (error: TResError | unknown) => {
      const resError = error as TResError;
      doSetError(resError.message);
      navigate('/login', { replace: true });
    },
  });
  const logoutUser = useLogoutUserMutation({
    onSuccess: (data) => {
      // Drop only the non-secret authentication sentinel.
      try { localStorage.removeItem('bs:auth-state'); } catch { /* ignore */ }
      const thirdPartyLogoutUrl = localStorage.getItem('THIRD_PARTY_LOGOUT_URL');
      if (thirdPartyLogoutUrl) {
        window.location.href = thirdPartyLogoutUrl;
        return;
      }
      setUserContext({
        token: undefined,
        isAuthenticated: false,
        // user: undefined,
        redirect: getPlatformAdminPanelUrl(),
      });
    },
    onError: (error) => {
      try { localStorage.removeItem('bs:auth-state'); } catch { /* ignore */ }
      const message = translate('platformAuth.localLogoutUnconfirmed');
      doSetError(message);
      window.showToast?.({ message, status: 'warning' });
      const thirdPartyLogoutUrl = localStorage.getItem('THIRD_PARTY_LOGOUT_URL');
      if (thirdPartyLogoutUrl) {
        window.location.href = thirdPartyLogoutUrl;
        return;
      }
      setUserContext({
        token: undefined,
        isAuthenticated: false,
        user: undefined,
        redirect: bsConfig?.host,
      });
    },
  });
  const [authReady, setAuthReady] = useState(false);
  useEffect(() => {
    let active = true;
    const initialize = () => {
      void platformAuth.initialize().then(() => {
        if (active) { setHostPending(platformAuth.hostPending); setAuthReady(!platformAuth.hostPending); setStartupFailed(false); }
      }).catch(() => {
        if (active) { setStartupFailed(true); doSetError(translate('platformAuth.serviceUnavailable')); }
      });
    };
    initialize();
    window.addEventListener('online', initialize);
    const unsubscribe = platformAuth.subscribe(event => {
      if (!active || !event || event.type === 'refresh') return;
      void queryClient.cancelQueries();
      queryClient.clear();
      setUser(undefined);
      setIsAuthenticated(false);
      setToken(undefined);
      if (event.type === 'login') { setAuthReady(false); initialize(); }
      else setAuthReady(true);
    });
    return () => { active = false; unsubscribe(); window.removeEventListener('online', initialize); };
  }, [setUser, queryClient, doSetError, translate]);
  const logout = useCallback(() => logoutUser.mutate(undefined), [logoutUser]);
  const userQuery = useGetUserQuery({ enabled: authReady });
  const mutateLogin = loginUser.mutate;
  const login = useCallback((data: t.TLoginUser) => { mutateLogin(data); }, [mutateLogin]);
  const silentRefresh = useCallback(() => {
    if (authConfig?.test || platformAuth.snapshot?.refresh_mode !== 'cookie') return;
    void platformAuth.refresh().catch((cause: unknown) => doSetError(translate(
      (cause as { status?: number }).status === 401 ? 'platformAuth.sessionEnded' : 'platformAuth.serviceUnavailable')));
  }, [authConfig?.test, doSetError, translate]);

  useEffect(() => {
    if (userQuery.data) {
      setUser(userQuery.data);
      setIsAuthenticated(true);
      // Keep a non-secret identity marker; authentication never clears user preferences.
      try {
        const uid = String(userQuery.data.id ?? '');
        if (uid && localStorage.getItem('bs:auth-state') !== uid) {
          localStorage.setItem('bs:auth-state', uid);
        }
      } catch { /* ignore storage errors */ }
    } else if (userQuery.isError) {
      doSetError((userQuery.error as Error).message);
      // navigate(`/${__APP_ENV__.BISHENG_HOST}`, { replace: true });
    }
    if (error != null && error && isAuthenticated) {
      doSetError(undefined);
    }
    if (token == null || !token || !isAuthenticated) {
      silentRefresh();
    }
  }, [
    token,
    isAuthenticated,
    userQuery.data,
    userQuery.isError,
    userQuery.error,
    error,
    setUser,
    navigate,
    silentRefresh,
    setUserContext,
    doSetError,
  ]);

  const refetchUser = userQuery.refetch;
  useEffect(() => {
    const handleTokenUpdate = () => {
      if (platformAuth.snapshot?.refresh_mode !== 'host') return;
      void platformAuth.initialize(true).then(session => {
        if (session?.refresh_mode === 'host') void refetchUser();
      }).catch(() => undefined);
    };

    window.addEventListener('tokenUpdated', handleTokenUpdate);

    return () => {
      window.removeEventListener('tokenUpdated', handleTokenUpdate);
    };
  }, [refetchUser]);

  // Consider "still loading" in two cases:
  // 1. The query hasn't completed yet (!isFetched)
  // 2. The query succeeded with data, but the useEffect that syncs
  //    userQuery.data → Recoil `user` atom hasn't fired yet (render gap)
  const isUserLoading = !authReady || (platformAuth.snapshot?.refresh_mode === 'host' && userQuery.isError) || !userQuery.isFetched || (userQuery.isSuccess && !user);

  // Make the provider update only when it should
  const memoedValue = useMemo(
    () => ({
      user,
      token,
      error,
      login,
      logout,
      setError,
      roles: {
        [SystemRoles.USER]: userRole,
        [SystemRoles.ADMIN]: adminRole,
      },
      isAuthenticated,
      isUserLoading,
    }),

    [user, error, isAuthenticated, token, userRole, adminRole, isUserLoading, login, logout],
  );

  return <AuthContext.Provider value={memoedValue}>{authReady ? children : (startupFailed || hostPending) ? <div role="status">
    {translate(hostPending ? 'platformAuth.hostReconnect' : 'platformAuth.serviceUnavailable')}
    <button type="button" onClick={() => hostPending ? requestHostAuthRenewal() : location.reload()}>{translate('platformAuth.retry')}</button>
  </div> : null}</AuthContext.Provider>;
};

const useAuthContext = () => {
  const context = useContext(AuthContext);

  if (context === undefined) {
    throw new Error('useAuthContext should be used inside AuthProvider');
  }

  return context;
};

export { AuthContextProvider, useAuthContext, AuthContext };
