import { useContext, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { userContext } from '../../contexts/userContext';
import { logoutApi } from '../../controllers/API/user';
import { captureAndAlertRequestErrorHoc } from '../../controllers/request';

/**
 * zz customization: a dedicated /logout URL so external portals can log the
 * user out of the admin console with a plain link.
 */
export default function LogoutPage() {
    const navigate = useNavigate();
    const { setUser } = useContext(userContext);

    useEffect(() => {
        const performLogout = async () => {
            try {
                await captureAndAlertRequestErrorHoc(logoutApi());
                setUser(null);
                localStorage.removeItem('isLogin');
                navigate('/login', { replace: true });
            } catch (error) {
                console.error('Logout failed:', error);
                // Force back to the login page even when the API call fails
                setUser(null);
                localStorage.removeItem('isLogin');
                navigate('/login', { replace: true });
            }
        };

        performLogout();
    }, [navigate, setUser]);

    return (
        <div className="flex items-center justify-center h-screen">
            <div className="text-center">
                <p className="text-gray-500">正在退出登录...</p>
            </div>
        </div>
    );
}
