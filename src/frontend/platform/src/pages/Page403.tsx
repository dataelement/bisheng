import { useState } from 'react';
import { logoutApi } from '@/controllers/API/user';

export default function Page403() {
    const [loggingOut, setLoggingOut] = useState(false);

    const clearLocalSession = () => {
        localStorage.removeItem('isLogin');
        localStorage.removeItem('ws_token');
        localStorage.removeItem('UUR_INFO');
        localStorage.removeItem('LOGIN_PATHNAME');
    };

    const handleLogout = async () => {
        if (loggingOut) return;
        setLoggingOut(true);

        const thirdPartyLogoutUrl = localStorage.getItem('THIRD_PARTY_LOGOUT_URL');

        try {
            await logoutApi();
        } catch {
            // 本地缓存仍需清理，避免无权限账号卡在 /403 无法切换账号。
        } finally {
            clearLocalSession();
            window.location.href = thirdPartyLogoutUrl || __APP_ENV__.BASE_URL + '/';
        }
    };

    return (
        <div className="fixed left-0 top-0 z-50 flex h-full w-full items-center justify-center bg-black bg-opacity-70">
            <div className="flex w-[90%] max-w-lg text-center min-h-[200px] flex-col justify-center rounded-lg p-8 shadow-xl bg-gray-50">
                <h1 className="mb-4 text-4xl font-bold text-red-600">
                    403
                </h1>
                <p className="mb-8 text-lg text-gray-800">
                    您无权访问该页面
                </p>
                <div className="flex justify-center">
                    <button
                        className="rounded bg-blue-500 px-6 py-2 text-sm font-semibold hover:bg-blue-600 text-gray-50"
                        disabled={loggingOut}
                        onClick={handleLogout}
                    >
                        {loggingOut ? '正在退出...' : '切换账号'}
                    </button>
                </div>
            </div>
        </div>
    );
};
