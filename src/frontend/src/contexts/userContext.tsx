import { toast } from "@/components/bs-ui/toast/use-toast";
import { ReactNode, createContext, useLayoutEffect, useState } from "react";
import { delComponentApi, getComponents, overridComponent, saveComponent } from "../controllers/API";
import { getUserInfo, logoutApi } from "../controllers/API/user";
import { captureAndAlertRequestErrorHoc, requestInterceptor } from "../controllers/request";
import { User } from "../types/api/user";

type userContextType = {
    user: any; // {} loading null login
    setUser: (newState: User) => void;
    savedComponents: any;
    addSavedComponent: (newCom: any, overrid: boolean, rename?: boolean) => Promise<any>;
    checkComponentsName: (name: string) => boolean;
    delComponent: (name: string) => void;
}

// const userInfoLocalStr = localStorage.getItem('UUR_INFO')
const initialValue = {
    user: {}, // userInfoLocalStr ? JSON.parse(atob(userInfoLocalStr)) : null,
    setUser: () => { },
    savedComponents: [],
    addSavedComponent: () => null,
    checkComponentsName: () => false,
    delComponent: () => { }
}

export const userContext = createContext<userContextType>(initialValue);

export function UserProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<any>(initialValue.user);
    const [savedComponents, setSavedComponents] = useState([]);

    const loadComponents = async () => {
        const res = await getComponents()
        setSavedComponents(res)
    }

    // 重名校验
    const checkComponentsName = (name: string) => {
        return savedComponents.some(item => item.name === name)
    }

    const addSavedComponent = (component: any, overrid: boolean, rename: boolean = true) => {
        // return delComponent(component.type)
        const nodeName = component.node.display_name
        const newNode = {
            ...component, node: { ...component.node, official: false }
        }

        const data = {
            name: nodeName,
            data: newNode,
            description: ''
        }
        // 覆盖
        if (overrid) {
            return captureAndAlertRequestErrorHoc(overridComponent(data)).then(res => {
                setSavedComponents((comps =>
                    comps.map(comp =>
                        comp.name === data.name ? data : comp
                    )
                ))
            })
        } else {
            // 重命名
            if (rename) {
                const regex = /\((\d+)\)$/;
                do {
                    const match = data.name.match(regex);
                    if (match) {
                        // 如果找到匹配项，将数字提取出来，转换成数字类型，并加1
                        const num = parseInt(match[1], 10) + 1;
                        data.name = data.name.replace(regex, `(${num})`);
                    } else {
                        data.name += "(1)";
                    }
                } while (savedComponents.some(item => item.name === data.name))
            }
            return captureAndAlertRequestErrorHoc(saveComponent(data)).then(sucess => {
                sucess && setSavedComponents([...savedComponents, data])
            })
        }
    }

    // del
    const delComponent = (name) => {
        delComponentApi(name).then(res => {
            setSavedComponents(comps => comps.filter(item => item.name !== name))
        })
    }

    useLayoutEffect(() => {
        // 链接ar参数存cookie（免登录接口）
        const cookie = location.search.match(/(?<=token=)[^&]+/g)?.[0]
        if (cookie) {
            document.cookie = `access_token_cookie=${cookie}; path=/`;
            localStorage.setItem('isLogin', '1')
            location.href = location.origin + location.pathname;
            return
        }

        // 异地登录强制退出
        requestInterceptor.remoteLoginFuc = (msg) => {
            logoutApi().then(_ => {
                setUser(null)
                localStorage.removeItem('isLogin')
            })

            toast({
                title: '提示',
                description: msg.split(`\n`),
                variant: 'error'
            })
        }
        // 获取用户信息
        getUserInfo().then(res => {
            setUser(res.user_id ? res : null)
            localStorage.setItem('UUR_INFO', res.user_id ? String(res.user_id) : '')
            if (res.user_id) loadComponents()
        }).catch(e => {
            setUser(null)
        })
    }, [])

    return (
        <userContext.Provider
            value={{
                user, setUser, savedComponents, checkComponentsName, delComponent, addSavedComponent
            }}
        >
            {children}
        </userContext.Provider>
    );
}