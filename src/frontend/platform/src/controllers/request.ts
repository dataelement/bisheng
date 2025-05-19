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
    if (response.data.status_code === 200) {
        return response.data.data;
    }
    const i18Msg = i18next.t(`errors.${response.data.status_code}`)
    const errorMessage = i18Msg === `errors.${response.data.status_code}` ? response.data.status_message : i18Msg

    // 无权访问
    if (response.data.status_code === 403) {
        // 修改不跳转
        if (response.config.method === 'get') {
            location.href = __APP_ENV__.BASE_URL + '/403'
        }
        return Promise.reject(errorMessage);
    }
    // 异地登录
    if (response.data.status_code === 10604) {
        requestInterceptor.remoteLoginFuc(response.data.status_message)
        return Promise.reject(errorMessage);
    }
    return Promise.reject(errorMessage);
}, function (error) {
    console.error('application error :>> ', error);
    if (error.response?.status === 401) {
        // cookie expires
        console.error('登录过期 :>> ');
        const UUR_INFO = 'UUR_INFO'
        const infoStr = localStorage.getItem(UUR_INFO)
        localStorage.removeItem(UUR_INFO)
        infoStr && location.reload()
        return Promise.reject('登录过期,请重新登录');
    }
    if (error.code === "ERR_CANCELED") return Promise.reject(null);
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

        console.log('error :>> ', error);
        iocFunc?.(error)
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
