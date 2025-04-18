// import ReactMarkdown from "react-markdown";
// import { CodeBlock } from "../../modals/formModal/chatMessage/codeBlock";

// let data = `

// ## 模型

// ### Multilingual E5 Large
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "embedding.ME5Embedding",
//       "gpu_memory": "3",
//       "instance_groups": "device=gpu;gpus=7|8"
//     }
//   }
//   \`\`\`
// - **状态**: ready/unready
// - **操作**: on/off/reload
// - **协议**: MIT

// ### BGE Large Chinese
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "embedding.BGEZhEmbedding",
//       "gpu_memory": "3",
//       "instance_groups": "device=gpu;gpus=7"
//     }
//   }
//   \`\`\`
// - **状态**: ready/unready
// - **协议**: MIT

// ### GTE Large
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "embedding.GTEEmbedding",
//       "gpu_memory": "3",
//       "instance_groups": "device=gpu;gpus=7"
//     }
//   }
//   \`\`\`
// - **状态**: ready/unready
// - **协议**: MIT

// ### Baichuan 13B Chat
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "llm.BaichuanChat",
//       "pymodel_params": "{\"max_tokens\": 4096}",
//       "gpu_memory": "30",
//       "instance_groups": "device=gpu;gpus=7,8"
//     }
//   }
//   \`\`\`
// - **协议**: Authorized

// ### ChatGLM2 6B and 6B 32K
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "llm.ChatGLM2",
//       "gpu_memory": "15",
//       "instance_groups": "device=gpu;gpus=7"
//     }
//   }
//   \`\`\`
// - **协议**: Authorized

// ### Llama 2 13B Chat and 7B Chat
// - **配置示例** (Llama 2 13B Chat):
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "llm.Llama2Chat",
//       "gpu_memory": "30",
//       "instance_groups": "device=gpu;gpus=7,8"
//     }
//   }
//   \`\`\`
// - **配置示例** (Llama 2 7B Chat):
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "llm.Llama2Chat",
//       "gpu_memory": "15",
//       "instance_groups": "device=gpu;gpus=7"
//     }
//   }
//   \`\`\`
// - **协议**: Authorized

// ### Qwen 7B Chat
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "llm.QwenChat",
//       "gpu_memory": "15",
//       "instance_groups": "device=gpu;gpus=7"
//     }
//   }
//   \`\`\`
// - **协议**: Authorized

// ### VisualGLM 6B
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.huggingface_model",
//       "pymodel_type": "mmu.VisualGLM",
//       "gpu_memory": "16",
//       "instance_groups": "device=gpu;gpus=7"
//     }
//   }
//   \`\`\`
// - **协议**: Authorized

// ## VisualGLM-6B License

// ### Element Layout V1
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.elem_model",
//       "pymodel_type": "layout.LayoutMrcnn",
//       "gpu_memory": "4",
//       "instance_groups": "device=gpu;gpus=6"
//     }
//   }
//   \`\`\`
// - **协议**: DataElem, Inc.

// ### Element Table Detect V1
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.elem_model",
//       "pymodel_type": "table.MrcnnTableDetect",
//       "gpu_memory": "4",
//       "instance_groups": "device=gpu;gpus=6"
//     }
//   }
//   \`\`\`
// - **协议**: DataElem, Inc.

// ### Element Table Cell Detect V1
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.elem_model",
//       "pymodel_type": "table.TableCellApp",
//       "gpu_memory": "4",
//       "instance_groups": "device=gpu;gpus=6"
//     }
//   }
//   \`\`\`
// - **协议**: DataElem, Inc.

// ### Element Table RowCol Detect V1
// - **配置示例**:
//   \`\`\`json
//   {
//     "parameters": {
//       "type": "dataelem.pymodel.elem_model",
//       "pymodel_type": "table.TableRowColApp",
//       "gpu_memory": "4",
//       "instance_groups": "device=gpu;gpus=6"
//     }
//   }
//   \`\`\`
// - **协议**: DataElem, Inc.

// `

// data = data.replaceAll('xxx', '\`\`\`')

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

