import { toast } from "@/components/bs-ui/toast/use-toast";
import axios from "axios";
import i18next from "i18next";
axios.defaults.withCredentials = true;
const customAxios = axios.create({
    baseURL: import.meta.env.BASE_URL
    // 配置
});
export const requestInterceptor = {
    remoteLoginFuc(msg) { }
};

customAxios.interceptors.request.use(function (config) {
    const token = localStorage.getItem('ws_token');
    if (token && !/^\/bisheng/.test(config.url)) {
        config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
}, function (error) {
    return Promise.reject(error);
});

customAxios.interceptors.response.use(function (response) {
    if (response.data instanceof Blob) return response.data;
    if (response.data.status_code === 200) {
        return response.data.data;
    }
    if (response.data.status_code === 11010) {
        return response.data;
    }
    // Silent mode: skip all global error handling, let the caller handle it
    if (response.config.silent) {
        return Promise.reject(response.data);
    }
    const statusCode = response.data.status_code
    const statusMessage = String(response.data.status_message || "")
    const i18Msg = i18next.t(`errors.${statusCode}`, response.data.data)

    const statusMessageKeyMap: Record<string, string> = {
        "person id already exists": "errors.personIdAlreadyExists",
        "department name already exists at this level": "errors.21001",
        "department not found": "errors.21000",
        "cannot delete department with children": "errors.21002",
        "cannot delete department with members": "errors.21003",
        "cannot move department to its own subtree": "errors.21004",
        "third-party synced department is read-only": "errors.21005",
        "root department already exists for this tenant": "errors.21006",
        "user is already a member of this department": "errors.21007",
        "user is not a member of this department": "errors.21008",
        "no permission for this department operation": "errors.21009",
        "password must be at least 8 characters and include upper, lower, digit and symbol": "errors.21010",
        "one or more roles are not assignable in this department": "errors.21011",
        "cannot delete user while data assets exist": "errors.21014",
        "only local accounts may be deleted from organization management": "errors.21015",
        "only archived departments can be permanently deleted": "errors.21016",
        "archived departments cannot be modified": "errors.21017",
        "cannot restore department while parent department is archived": "errors.21018",
    }

    const normalizedStatusMessage = statusMessage.trim().toLowerCase()
    const mappedStatusMessageKey = statusMessageKeyMap[normalizedStatusMessage]
    const i18MsgFromStatus = mappedStatusMessageKey
        ? i18next.t(mappedStatusMessageKey, response.data.data)
        : null

    const errorMessage =
        i18Msg !== `errors.${statusCode}`
            ? i18Msg
            : (i18MsgFromStatus && i18MsgFromStatus !== mappedStatusMessageKey
                ? i18MsgFromStatus
                : statusMessage)

    // 密码过期，标记后透传给业务层处理
    if (statusCode === 10601) {
        return Promise.reject({ code: 10601, message: errorMessage });
    }
    // 无权访问
    if ([403, 404].includes(statusCode) && response.config.url !== '/api/v1/user/info') {
        // 修改不跳转
        localStorage.setItem('noAccessUrl', response.request.responseURL)
        if (response.config.method === 'get') {
            location.href = __APP_ENV__.BASE_URL + '/' + statusCode
        }
        return Promise.reject(errorMessage);
    }
    // 应用无编辑权限 (TODO业务状态码放行到具体业务中)
    if ([10599, 17005].includes(statusCode)) {
        location.href = `${__APP_ENV__.BASE_URL}/build/apps?error=${statusCode}`
        return Promise.reject(errorMessage);
    }
    // 异地登录
    if (response.data.status_code === 10604) {
        const thirdPartyLoginUrl = localStorage.getItem('THIRD_PARTY_LOGIN_URL');
        if (thirdPartyLoginUrl) {
            window.location.href = thirdPartyLoginUrl;
            return Promise.reject(errorMessage);
        }
        requestInterceptor.remoteLoginFuc(response.data.status_message)
        return Promise.reject(errorMessage);
    }
    return Promise.reject(errorMessage);
}, function (error) {
    console.error('application error :>> ', error);
    if (error.response?.status === 401) {
        // 必须在 remove 之前读取：从未持有 ws_token/UUR_INFO 时 401（如登录页拉 /user/info）不应整页跳转，否则会死循环。
        const hadSession =
            !!localStorage.getItem('ws_token')
            || !!localStorage.getItem('UUR_INFO');
        // cookie / Bearer 失效（含 token_version 失效、账号禁用）
        localStorage.removeItem('ws_token');
        console.error('登录过期 :>> ');
        const thirdPartyLoginUrl = localStorage.getItem('THIRD_PARTY_LOGIN_URL');
        if (thirdPartyLoginUrl) {
            localStorage.removeItem('UUR_INFO');
            window.location.href = thirdPartyLoginUrl;
            return Promise.reject('登录过期');
        }
        localStorage.removeItem('UUR_INFO');
        // 仅「曾有过登录态」时再回根路径，避免深路径 URL 上叠登录页且状态错乱。
        if (hadSession) {
            const base = (__APP_ENV__.BASE_URL || '').replace(/\/$/, '');
            window.location.href = `${base}/`;
        }
        return Promise.reject('登录过期,请重新登录');
    }
    if (error.code === "ERR_CANCELED") return Promise.reject(error);
    // Silent mode: skip toast, let the caller handle it
    if (error.config?.silent) return Promise.reject(error);
    // app 弹窗
    toast({
        title: `${i18next.t('prompt')}`,
        variant: 'error',
        description: error.message
    })
    // window.errorAlerts([error.message])
    return Promise.reject(null);
})

export default customAxios


// 接口异常提示弹窗
export function captureAndAlertRequestErrorHoc(apiFunc, iocFunc?) {
    return apiFunc.catch(error => {
        if (error === null) return // app error
        if (error?.code === "ERR_CANCELED") return 'canceled'

        console.log('error :>> ', error);
        // If iocFunc returns true, it means the caller has handled the error itself (e.g. showing its own toast)
        const handled = iocFunc?.(error)
        if (handled) return false

        // 弹窗
        toast({
            title: `${i18next.t('prompt')}`,
            variant: 'error',
            description: typeof error === 'string' ? error : JSON.stringify(error)
        })
        console.error('逻辑异常 :>> ', error);
        return false
    })
};
