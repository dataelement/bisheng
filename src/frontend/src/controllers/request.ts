import axios from "axios";

axios.defaults.withCredentials = true;

const customAxios = axios.create({
    // 配置
});

customAxios.interceptors.response.use(function (response) {
    if (response.data.status_code === 200) {
        return response.data.data;
    }
    return Promise.reject(response.data.status_message);
}, function (error) {
    console.error('application error :>> ', error);
    if (error.response?.status === 401) {
        // cookie expires
        console.error('登录过期 :>> ');
        const UUR_INFO = 'UUR_INFO'
        const infoStr = localStorage.getItem(UUR_INFO)
        localStorage.removeItem(UUR_INFO)
        infoStr && location.reload()
        return Promise.reject(error);
    }
    // app 弹窗
    window.errorAlerts([error.message])
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
        window.errorAlerts([error])
        console.error('逻辑异常 :>> ', error);
        return false
    })
};
