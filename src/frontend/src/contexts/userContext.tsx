import { ReactNode, createContext, useLayoutEffect, useState } from "react";
import { getUserInfo } from "../controllers/API/user";
import { User } from "../types/api/user";

type userContextType = {
    user: any; // {} loading null login
    setUser: (newState: User) => void;
}

// const userInfoLocalStr = localStorage.getItem('UUR_INFO')
const initialValue = {
    user: {}, // userInfoLocalStr ? JSON.parse(atob(userInfoLocalStr)) : null,
    setUser: () => { }
}

export const userContext = createContext<userContextType>(initialValue);

export function UserProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<any>(initialValue.user);

    useLayoutEffect(() => {
        // 链接ar参数存cookie（免登录接口）
        const cookie = location.search.match(/(?<=token=)[^&]+/g)?.[0]
        if (cookie) {
            document.cookie = `access_token_cookie=${cookie}`;
            localStorage.setItem('isLogin', '1')
            location.href = location.origin + location.pathname;
            return
        }

        getUserInfo().then(res => {
            setUser(res.user_id ? res : null)
            localStorage.setItem('UUR_INFO', res.user_id ? String(res.user_id) : '')
        }).catch(e => {
            setUser(null)
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