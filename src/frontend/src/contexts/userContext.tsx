import { ReactNode, createContext, useEffect, useState } from "react";
import { getUserInfo } from "../controllers/API/user";

type userContextType = {
    user: any;
    setUser: (newState: any) => void;
}

// const userInfoLocalStr = localStorage.getItem('UUR_INFO')
const initialValue = {
    user: null, // userInfoLocalStr ? JSON.parse(atob(userInfoLocalStr)) : null,
    setUser: () => { }
}

export const userContext = createContext<userContextType>(initialValue);

export function UserProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState(initialValue.user);

    useEffect(() => {
        getUserInfo().then(res => {
            setUser(res.data.user_id ? res.data : {})
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