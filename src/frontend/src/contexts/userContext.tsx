import { ReactNode, createContext, useState } from "react";

type userContextType = {
    user: any;
    setUser: (newState: any) => void;
}

const userInfoLocalStr = localStorage.getItem('UUR_INFO')
const initialValue = {
    user: userInfoLocalStr ? JSON.parse(atob(userInfoLocalStr)) : null,
    setUser: () => { }
}

console.log('initialValue :>> ', initialValue);

export const userContext = createContext<userContextType>(initialValue);

export function UserProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState(initialValue.user);

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