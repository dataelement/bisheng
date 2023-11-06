import { ReactNode, createContext, useState } from "react";
import { User } from "../types/app";

type userContextType = {
    user: User;
    setUser: (newState: User) => void;
}

const userInfoLocalStr = localStorage.getItem('UUR_INFO')
const initialValue = {
    user: userInfoLocalStr ? JSON.parse(atob(userInfoLocalStr)) : null,
    setUser: () => { }
}

export const userContext = createContext<userContextType>(initialValue);

export function UserProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User>(initialValue.user);

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