// @ts-strict-ignore
import { toast } from "@/components/bs-ui/toast/use-toast";
import { resolveAdminLandingPath, resolveRoutePermissions } from "@/routes";
import { getWorkspaceClientUrl } from "@/utils/workspaceUrl";
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

type PlatformEntry = 'platform' | 'workspace' | 'forbidden'

interface PlatformEntryUser {
    role?: string
    has_admin_console?: boolean | null
    has_workbench?: boolean | null
    is_department_admin?: boolean | null
    can_manage_user_groups?: boolean | null
}

export function resolvePlatformEntry(user: PlatformEntryUser, webMenu: string[]): PlatformEntry {
    const adminMenuKeys = new Set([
        'backend',
        'admin',
        'board',
        'model',
        'log',
        'knowledge',
        'build',
        'evaluation',
        'system_config',
        'mark_task',
    ])
    const canAccessPlatform =
        user.has_admin_console
        ?? (
            user.role === 'admin'
            || Boolean(user.is_department_admin)
            || Boolean(user.can_manage_user_groups)
            || webMenu.some((key) => adminMenuKeys.has(key))
        )
    if (canAccessPlatform) return 'platform'

    const canAccessWorkspace =
        user.has_workbench
        ?? (
            webMenu.includes('workstation')
            || webMenu.includes('frontend')
        )
    return canAccessWorkspace ? 'workspace' : 'forbidden'
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
        // record workspace auth
        const search = location.search;
        const params = new URLSearchParams(search);
        const error = params.get('error');
        if (error) {
            window.url_error = error;
        }

        // 异地登录强制退出
        requestInterceptor.remoteLoginFuc = (msg) => {
            logoutApi().then(_ => {
                const thirdPartyLogoutUrl = localStorage.getItem('THIRD_PARTY_LOGOUT_URL')
                localStorage.removeItem('isLogin')
                if (thirdPartyLogoutUrl) {
                    window.location.href = thirdPartyLogoutUrl
                    return
                }
                setUser(null)
            })

            toast({
                description: msg.split(`\n`),
                variant: 'error'
            })
        }
        // 获取用户信息
        getUserInfo().then(res => {
            setUser(res.user_id ? res : null)
            const { user_id } = res;
            // Apply the same Child Admin compatibility grants used by the route layer.
            const web_menu: string[] = resolveRoutePermissions(res);

            localStorage.setItem('UUR_INFO', user_id ? String(user_id) : '');
            // if (user_id) loadComponents();
            // 是否有访问后台权限
            if (/^(\/\w+)?\/chat/.test(location.pathname)) return // 排除免登陆

            const BASE_URL = __APP_ENV__.BASE_URL

            const platformEntry = resolvePlatformEntry(res, web_menu)
            if (platformEntry !== 'platform') {
                if (platformEntry === 'forbidden') {
                    window.location.replace(getWorkspaceClientUrl('/menu-unavailable'))
                    return
                }
                // Hard-navigate to the workspace client. Must NOT use history.back()
                // here: under the SSO flow the previous history entry is the IdP /
                // portal page, so "going back" silently re-triggers SSO and produces
                // an infinite redirect loop for non-admin users. replace() also drops
                // the un-usable platform URL from history.
                window.location.replace(getWorkspaceClientUrl('/'))
                return
            }

            const pathName = location.pathname.replace(BASE_URL, '');

            // Jump to the route based on permissions
            if (pathName === '/admin') {
                const adminApprovalMode = Boolean(res.menu_approval_mode_admin ?? res.menu_approval_mode);
                const target = resolveAdminLandingPath(web_menu, adminApprovalMode);
                history.pushState(null, '', BASE_URL + target);
            } else {
                // 403
                const MENU_KEY_MAP: Record<string, string> = {
                    '/dashboard': 'board',
                    '/build/apps': 'build',
                    '/filelib': 'knowledge',
                    '/dataset': 'dataset',
                    '/model/management': 'model',
                    '/evaluation': 'evaluation',
                    '/label': 'mark_task',
                    '/log': 'log',
                }
                const normalizedPath = pathName.replace(/\/+$/, '') || '/'
                let menuName = MENU_KEY_MAP[normalizedPath]
                if (!menuName && normalizedPath.startsWith('/label')) {
                    menuName = 'mark_task'
                }
                if (!menuName && normalizedPath.startsWith('/log')) {
                    menuName = 'log'
                }
                if (
                    menuName
                    && res.role !== 'admin'
                    && !web_menu.includes(menuName)
                    && !(res.menu_approval_mode_admin ?? res.menu_approval_mode)
                ) {
                    history.pushState(null, '', BASE_URL + '/403');
                }
            }
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
