import { ReactNode, createContext, useEffect, useLayoutEffect, useState } from "react";
import { getUserInfo } from "../controllers/API/user";

type userContextType = {
    user: any;
    setUser: (newState: any) => void;
}

// const userInfoLocalStr = localStorage.getItem('UUR_INFO')
const initialValue = {
    user: {}, // userInfoLocalStr ? JSON.parse(atob(userInfoLocalStr)) : null,
    setUser: () => { }
}

export const userContext = createContext<userContextType>(initialValue);

export function UserProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState(initialValue.user);

    useLayoutEffect(() => {
        // 链接ar参数存cookie（免登录接口）
        const cookie = location.search.match(/(?<=token=)[^&]+/g)?.[0]
        if (cookie) {
            document.cookie = `access_token_cookie=${cookie}`;
            location.href = location.origin + location.pathname;
            return
        }

        getUserInfo().then(res => {
            setUser(res.data.user_id ? res.data : null)
        })
    }, [])

    return (
        <userContext.Provider
            value={{
                user, setUser
            }}
        >
            {children}
        </userContext.Provider>
    );
}