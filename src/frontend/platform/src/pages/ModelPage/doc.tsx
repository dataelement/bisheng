
import { useEffect } from "react";

export default function Doc() {
    // const [loading, setLoading] = useState(true)

    useEffect(() => {
        var link = __APP_ENV__.BASE_URL + '/doc.pdf'

        var iframe: any = document.getElementById('iframe')

        // if (navigator.userAgent.match(/Android/i) || navigator.userAgent.match(/iPhone|iPad|iPod/i)) {
        //     iframe.src = '/pdf/web/viewer.html?file=' + location.search.split('=')[1];
        // } else {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', link, true);
        xhr.responseType = 'blob';
        xhr.onload = function () {
            // setLoading(false)
            if (this.status === 200) {
                var blob = new Blob([this.response], { type: 'application/pdf' });
                var url = URL.createObjectURL(blob);
                if (iframe) iframe.src = url;
            }
        };
        xhr.onerror = function () {
            // setLoading(false)
            // $message.error('文件加载异常')
        }
        xhr.send();
        // }
    }, [])

    return <div style={{ width: "100%", height: "100vh" }}>
        {/* <iframe id="iframe" style={{ width: "100%", height: "100%" }} src="" ></iframe> */}
        {/* <h1>正在加载文件</h1> */}
        {/* {loading && <Loading color="secondary" size="xs" />} */}
        <iframe id="iframe" style={{ width: "100%", height: "100%" }} src="" ></iframe>
    </div>
};

