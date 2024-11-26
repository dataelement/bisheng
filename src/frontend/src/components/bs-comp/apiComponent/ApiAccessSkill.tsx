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
import { useTranslation } from 'react-i18next';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";
import { JsonItem } from './ApiAccess';


const ApiAccessSkill = ({ }) => {
    const { t } = useTranslation()
    const { flow, getTweak, tabsState } = useContext(TabsContext);
    const curl_code = getCurlCode(flow, getTweak, tabsState);
    const pythonCode = getPythonApiCode(flow, getTweak, tabsState);

    const { message } = useToast()
    const handleCopyLink = (e) => {
        copyText(e.target).then(() => {
            message({ variant: 'success', description: t('api.copySuccess') })
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
                    <CardTitle>{t('api.apiRequestExample')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>/api/v1/process/{flow.id}</span>
                    </h3>
                    <p className='my-2'>{t('api.exampleCode')}：</p>
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
                    <CardTitle>{t('api.requestParams')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>
                                    {t('api.bodyParams')} <span className='bg-secondary px-2 py-1 rounded-md text-sm'>application/json</span>
                                </TableHead>
                                <TableHead>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <JsonItem name="flow_id" required type="UUID" desc={t('api.skillId')} remark={t('api.urlParam')}></JsonItem>
                                    <JsonItem name="inputs" required type="Json" desc={t('api.skillInput')} example='{"query":"什么是金融"}' remark={t('api.singleInput')} ></JsonItem>
                                    <JsonItem name="history_count" type="int" desc={t('api.historyCount')}></JsonItem>
                                    <JsonItem name="clear_cache" type="boolean" desc={t('api.clearCache')}></JsonItem>
                                    <JsonItem name="session_id" type="str" desc={t('api.sessionId')} remark={t('api.sessionRemark')}></JsonItem>
                                    <JsonItem name="tweaks" required type="Json" desc={t('api.tweaks')} remark={t('api.tweaksRemark')}>
                                        <JsonItem line name="ChatOpenAI-MzIaC" type="Json" desc={t('api.exampleComponent')} example='{"openai_api_key": "sk-xxx"} 或者 {}' remark={t('api.defaultConfig')} ></JsonItem>
                                        <JsonItem line name="..." type="Json" desc={t('api.componentParams')}></JsonItem>
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
                    <CardTitle>{t('api.responseData')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.dataStructure')}</TableHead>
                                <TableHead className='w-[40%]'>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <JsonItem name="data" type="object" desc={t('api.returnContent')}>
                                        <JsonItem line name="session_id" type="string" desc={t('api.sessionIdReturn')}></JsonItem>
                                        <JsonItem line name="result" type="object" desc={t('api.skillResult')}>
                                            <JsonItem line name="answer" type="string" desc={t('api.llmAnswer')}></JsonItem>
                                            <JsonItem line name="message_id" type="int" desc={t('api.messageId')}></JsonItem>
                                            <JsonItem line name="source" type="int" desc={t('api.source')}></JsonItem>
                                            <JsonItem line name="{key}" type="string" desc={t('api.dynamicKey')}></JsonItem>
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
      "result": "文档内容是关于电力集团关键信息基础设施网络安全保护的标准起草。文档以“基于管理防护要求”为主题，参考知识库内容，根据模版撰写相应内容。这份文档的撰写要求是不少于500字，不允许使用markdown格式，每行需要缩进两格。",
      "doc": [
        {
          "title": "关基网络安全保护工作指南.docx",
          "url": "www.baidu.com"
        }
      ],
      "source": 3,
      "message_id": 1322,
      "answer": "文档内容是关于电力集团关键信息基础设施网络安全保护的标准起草。文档以“基于管理防护要求”为主题，参考知识库内容，根据模版撰写相应内容。"
    },
    "session_id": "AUU629:059865218b3e895f103dbcad4d1b60ee40157191800f3aa8adaa12488f2cf82b",
    "backend": "anyio"
  }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>

            <Card className='mt-8'>
                <CardHeader>
                    <CardTitle>{t('api.useCase')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className="text-lg font-medium mb-2">{t('api.knowledgeQADemo')}</h3>
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
    api_url = f"{BASE_API_URL}/{flow_id}"
    payload = {"inputs": inputs}
    if tweaks:
        payload["tweaks"] = tweaks
    response = requests.post(api_url, json=payload)
    return response.json()
inputs = {"input":"什么是金融"}
print(run_flow(inputs, flow_id=FLOW_ID, tweaks=TWEAKS))`}
                    </SyntaxHighlighter>

                    <p className="text-md text-gray-500 mb-2">{t('api.specifyKnowledgeBase')}</p>
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

                    <h3 className="text-lg font-medium mb-2 mt-12">{t('api.reportGenerationDemo')}</h3>
                    <p className="text-md mb-2">{t('api.step1')}</p>
                    <p className="text-md text-gray-500 mb-2">
                        {t('api.dependenciesDescription')}
                    </p>
                    <p className="text-md mb-2">{t('api.step2')}</p>
                    <p className="text-md text-gray-500 mb-2">{t('api.uploadFiles')}</p>
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

                    <p className="text-md mb-2">{t('api.step3')}</p>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
                        language={'python'}
                        style={oneDark}
                    >
                        {`tweaks = {
  "InputFileNode-ozsI2": {"file_path": financeA},
  "InputFileNode-16U46": {"file_path": financeB},
  "Milvus-6HDPE": {"collection_name": "tmp", "drop_old": True} 
}`}
                    </SyntaxHighlighter>

                    <p className="text-md mb-2">{t('api.step4')}</p>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
                        language={'bash'}
                        style={oneDark}
                    >
                        {`response = requests.post(url="http://192.168.106.120:3002/api/v1/process/940a528f-eccc-4d43-aa19-55c4725645cf",
    json={"inputs": {"report_name":"","id":"Report-tuc6Q"}, "tweaks": tweaks})

print(response.text)`}
                    </SyntaxHighlighter>
                </CardContent>
            </Card>
        </section>

    );
};

export default ApiAccessSkill;
