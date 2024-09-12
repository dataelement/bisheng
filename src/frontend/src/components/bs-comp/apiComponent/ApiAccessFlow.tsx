import { Badge } from '@/components/bs-ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/bs-ui/tabs';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { getCurlCode, getPythonApiCode } from '@/constants';
import { TabsContext } from '@/contexts/tabsContext';
import { copyText } from '@/utils';
import { Check, Clipboard } from 'lucide-react';
import { useContext, useState } from 'react';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";
import { JsonItem } from './ApiAccess';


const ApiAccessFlow = ({ }) => {

    const { flow, getTweak, tabsState } = useContext(TabsContext);
    const curl_code = getCurlCode(flow, getTweak, tabsState);
    const pythonCode = getPythonApiCode(flow, getTweak, tabsState);

    const { message } = useToast()
    const handleCopyLink = (e) => {
        copyText(e.target).then(() => {
            message({ variant: 'success', description: '复制成功' })
        })
    }

    const [isCopied, setIsCopied] = useState<Boolean>(false);
    const copyToClipboard = (code: string) => {
        setIsCopied(true);
        copyText(code).then(() => {
            setTimeout(() => {
                setIsCopied(false);
            }, 2000);
        })
    }

    return (
        <section className='max-w-[1600px] flex-grow'>
            <Card className="mb-8">
                <CardHeader>
                    <CardTitle>API 请求示例</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>/api/v1/process/{flow.id}</span>
                    </h3>
                    <p className='my-2'>示例代码如下：</p>
                    <Tabs defaultValue="curl" className="w-full mb-[40px]">
                        <TabsList className="">
                            <TabsTrigger value="curl" className="">cURL</TabsTrigger>
                            <TabsTrigger value="python">Python API</TabsTrigger>
                        </TabsList>

                        <TabsContent value="curl" className='relative'>
                            <button
                                className="absolute right-0 flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                                onClick={() => copyToClipboard(curl_code)}
                            >
                                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
                            </button>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'bash'}
                                style={oneDark}
                            >
                                {curl_code}
                            </SyntaxHighlighter>
                        </TabsContent>
                        <TabsContent value="python" className='relative'>
                            <button
                                className="absolute right-0 flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                                onClick={() => copyToClipboard(pythonCode)}
                            >
                                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
                            </button>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'python'}
                                style={oneDark}
                            >
                                {pythonCode}
                            </SyntaxHighlighter>
                        </TabsContent>
                    </Tabs>
                </CardContent>
            </Card>

            <Card className="mb-8">
                <CardHeader>
                    <CardTitle>请求参数</CardTitle>
                </CardHeader>
                <CardContent>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>Body 参数: <span className='bg-secondary px-2 py-1 rounded-md text-sm'>application/json</span></TableHead>
                                <TableHead>示例</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <JsonItem name="flow_id" required type="UUID" desc="技能ID" remark='URL传参'></JsonItem>
                                    <JsonItem name="inputs" required type="Json" desc="对整个技能的问题输入，json里的具体key和技能本身相关，不一定都是query" example='{"query":"什么是金融"}' remark='当输入节点只有一个时，id可不传'></JsonItem>
                                    <JsonItem name="history_count" type="int" desc="对于技能里支持Memery，选取几条历史消息进行多轮问答，默认值10"></JsonItem>
                                    <JsonItem name="clear_cache" type="boolean" desc="是否清除session缓存"></JsonItem>
                                    <JsonItem name="session_id" type="str" desc="用于session查找，当我们进行多轮时，此参数必填，且建议采用后端生成的key" remark='每次调用，当session_id 传入时，返回传入sessionid，当session_id不传时，自动生成id'></JsonItem>
                                    <JsonItem name="tweaks" required type="Json" desc="对每个组件的控制，可以替换组件输入参数的值" remark='当没有指定组件传参的时候，可以不传'>
                                        <JsonItem line name="ChatOpenAI-MzIaC" type="Json" desc="示例，技能中OpenAI大模型组件的配置信息，key为组件名，命名为{组件}-{id}" example='{"openai_api_key": "sk-xxx"} 或者 {}' remark='当{}为空，表示保持默认值'></JsonItem>
                                        <JsonItem line name="..." type="Json" desc="每个技能中各个组件的参数均可以在调用接口时传进去，如果不传则用技能的默认配置"></JsonItem>
                                    </JsonItem>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className=" w-full overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "inputs": {
    "query": "总结下文档内容"
  },
  "tweaks": {
    "Milvus-f74d8": {
      "collection_id": "10"
    },
    "ChatOpenAI-7f49c": {},
    "ElasticKeywordsSearch-0d2c8": {},
    "BishengRetrievalQA-7e0ae": {}
  },
  "history_count": 10,
  "clear_cache": false
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle>返回响应</CardTitle>
                </CardHeader>
                <CardContent>
                    {/* <h3 className="text-lg font-medium mb-2">成功响应 (200)</h3> */}
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>数据结构</TableHead>
                                <TableHead className='w-[40%]'>示例</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <JsonItem name="data" type="object" desc='返回内容'>
                                        <JsonItem line name="session_id" type="string" desc='会话id，用来和入参对应'></JsonItem>
                                        <JsonItem line name="result" type="object" desc='技能返回的结果'>
                                            <JsonItem line name="answer" type="string" desc='技能统一key返回的LLM 内容'></JsonItem>
                                            <JsonItem line name="message_id" type="int" desc='技能历史消息存储id'></JsonItem>
                                            <JsonItem line name="source" type="int" desc='是否溯源： 0 不可溯源， 1 普通溯源， 2有访问权限，3/4 特殊情况下的溯源'></JsonItem>
                                            <JsonItem line name="{key}" type="string" desc='key是技能里组件定义的输出key，输出的内容和answer一致，唯一的区别是key不固定'></JsonItem>
                                        </JsonItem>
                                    </JsonItem>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "result": {
      "result": "文档内容是关于电力集团关键信息基础设施网络安全保护的标准起草。文档以“基于管理防护要求”为主题，参考知识库内容，根据模版撰写相应内容。这份文档的撰写要求是不少于500字，不允许使用markdown格式，每行需要缩进两格。\n\n文档的模板包括以下几个部分：4.3.1 网络安全建设管理要求，4.3.2 网络安全风险管理，4.3.3 和 4.3.4 这两部分的内容未给出。每一部分都由多个小点组成，每个小点后面都有\"xxxx....\"表示待填写的内容。",
      "doc": [
        {
          "title": "关基网络安全保护工作指南.docx",
          "url": "www.baidu.com"
        }
      ],
      "source": 3,
      "message_id": 1322,
      "answer": "文档内容是关于电力集团关键信息基础设施网络安全保护的标准起草。文档以“基于管理防护要求”为主题，参考知识库内容，根据模版撰写相应内容。这份文档的撰写要求是不少于500字，不允许使用markdown格式，每行需要缩进两格。\n\n文档的模板包括以下几个部分：4.3.1 网络安全建设管理要求，4.3.2 网络安全风险管理，4.3.3 和 4.3.4 这两部分的内容未给出。每一部分都由多个小点组成，每个小点后面都有\"xxxx....\"表示待填写的内容。"
    },
    "session_id": "AUU629:059865218b3e895f103dbcad4d1b60ee40157191800f3aa8adaa12488f2cf82b",
    "backend": "anyio"
  }
}`
                                        }
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>

            <Card className='mt-8'>
                <CardHeader>
                    <CardTitle>应用案例</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className="text-lg font-medium mb-2">知识库问答应用示例</h3>
                    <SyntaxHighlighter
                        className=" w-full overflow-auto custom-scroll"
                        language={'python'}
                        style={oneDark}
                    >
                        {`import requests
from typing import Optional
BASE_API_URL = "http://{IP}:{port}/api/v1/process"
FLOW_ID = "your flow_id"
# You can tweak the flow by adding a tweaks dictionary
# e.g {"OpenAI-XXXXX": {"model_name": "gpt-4"}}
TWEAKS = {
  "ConversationChain-A1J5d": {},
  "ProxyChatLLM-NloT5": {}
}
def run_flow(inputs: dict, flow_id: str, tweaks: Optional[dict] = None) -> dict:
    """
    Run a flow with a given message and optional tweaks.

    :param message: The message to send to the flow
    :param flow_id: The ID of the flow to run
    :param tweaks: Optional tweaks to customize the flow
    :return: The JSON response from the flow
    """
    api_url = f"{BASE_API_URL}/{flow_id}"
    payload = {"inputs": inputs}
    if tweaks:
        payload["tweaks"] = tweaks
    response = requests.post(api_url, json=payload)
    return response.json()
# Setup any tweaks you want to apply to the flow
inputs = {"input":"什么是金融"}
print(run_flow(inputs, flow_id=FLOW_ID, tweaks=TWEAKS))`}
                    </SyntaxHighlighter>

                    <p className="text-md text-gray-500 mb-2">如需指定知识库进行问答，可在传入参数时指定知识库 id，例如：</p>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
                        language={'python'}
                        style={oneDark}
                    >
                        {`TWEAKS = {
  "ConversationChain-A1J5d": {},
   "Milvus-T3kRH": {"collection_id": "your collection_id"},
  "ProxyChatLLM-NloT5": {}
}`}
                    </SyntaxHighlighter>

                    <h3 className="text-lg font-medium mb-2 mt-12">报告生成应用示例</h3>
                    <p className="text-md mb-2">step1：确认触发该技能执行的依赖项</p>
                    <p className="text-md text-gray-500 mb-2">依赖项即对应界面上会话页面中创建会话时左下角表单中的内容，对应技能编辑时使用的组件 <Badge variant='secondary'>inputFileNode</Badge>、<Badge variant='secondary'>variableNode</Badge>组件，例如下面示例中对应有两个文件上传组件：InputFileNode-16u46、InputFileNode-0zsI2</p>
                    <p className="text-md mb-2">step2：准备入参</p>
                    <p className="text-md text-gray-500 mb-2">本示例中入参为 2 个文件：</p>
                    <SyntaxHighlighter
                        className=" w-full overflow-auto custom-scroll"
                        language={'python'}
                        style={oneDark}
                    >
                        {`import requests
def upload_file(local_path: str):
    server = "http://ip:port"
    url = server + '/api/v1/knowledge/upload'
    headers = {}
    files = {'file': open(local_path, 'rb')}
    res = requests.post(url, headers=headers, files=files)
    file_path = res.json()['data'].get('file_path', '')
    return file_path
    
 financeA = upload_file("caibao.pdf")
 financeB = upload_file("caibao2.pdf")`}
                    </SyntaxHighlighter>
                    <p className="text-md mb-2">step3：组装 tweaks</p>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
                        language={'python'}
                        style={oneDark}
                    >
                        {`# 所有apidemo里没有更新的都可以删除，保持代码清晰
tweaks = {
  "InputFileNode-ozsI2": {"file_path": financeA},
  "InputFileNode-16U46": {"file_path": financeB},
  "Milvus-6HDPE": {"collection_name": "tmp", "drop_old": True} # 临时知识库，目前需要手动指定collection
}`}
                    </SyntaxHighlighter>
                    <p className="text-md mb-2">step4：执行技能</p>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
                        language={'bash'}
                        style={oneDark}
                    >
                        {`response = requests.post(url="http://192.168.106.120:3002/api/v1/process/940a528f-eccc-4d43-aa19-55c4725645cf",
    json={"inputs": {"report_name":"","id":"Report-tuc6Q"}, "tweaks": tweaks})


print(response.text)`}
                    </SyntaxHighlighter>
                    {/* <h3 className="text-lg font-medium mb-2 mt-12">文档审核应用示例</h3>
                    <p className="text-md text-gray-500 mb-2">期待你的大作@张国清 </p> */}
                </CardContent>
            </Card>
        </section>
    );
};

export default ApiAccessFlow;
