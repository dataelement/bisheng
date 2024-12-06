import { Alert, AlertDescription } from '@/components/bs-ui/alert';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import Skeleton from '@/components/bs-ui/skeleton';
import { copyText } from '@/utils';
import { Check, CircleX, Clipboard, Info } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";

const BorwserSkeleton = ({ size = '' }) => {
  return <div className="p-4 rounded-lg max-w-lg mx-auto">
    {/* 浏览器窗口的骨架 */}
    <div className="border border-border rounded-lg overflow-hidden">
      {/* 浏览器顶部导航栏骨架 */}
      <div className="p-2 bg-accent flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Skeleton className="h-4 w-4 rounded-full" /> {/* 浏览器左上角圆形图标 */}
          <Skeleton className="h-4 w-4 rounded-full" />
          <Skeleton className="h-4 w-4 rounded-full" />
        </div>
        <Skeleton className="h-4 w-1/2 rounded" /> {/* 浏览器地址栏骨架 */}
        <Skeleton className="h-4 w-4 rounded" /> {/* 浏览器右上角按钮 */}
      </div>

      {/* 聊天窗口的骨架 */}
      {
        size ? <div className="p-4 bg-white flex justify-end items-end">
          <div className="border w-[200px] rounded-lg p-4 space-y-4">
            <Skeleton className="h-4 w-3/4 rounded" /> {/* 聊天标题 */}
            <Skeleton className="h-44 w-full rounded" /> {/* 聊天内容区域 */}
            <div className="flex items-center">
              <Skeleton className="h-6 w-full rounded" /> {/* 输入框骨架 */}
              <Skeleton className="h-6 w-16 ml-2 rounded" /> {/* 发送按钮骨架 */}
            </div>
          </div>
          <CircleX className='h-6 w-6 text-foreground' />
        </div>
          : <div className="p-4 bg-white">
            <div className="border border-border rounded-lg p-4 space-y-4">
              <Skeleton className="h-6 w-3/4 rounded" /> {/* 聊天标题 */}
              <Skeleton className="h-40 w-full rounded" /> {/* 聊天内容区域 */}
              <div className="flex items-center">
                <Skeleton className="h-8 w-full rounded" /> {/* 输入框骨架 */}
                <Skeleton className="h-8 w-16 ml-2 rounded" /> {/* 发送按钮骨架 */}
              </div>
            </div>
          </div>
      }
    </div>
  </div>
}


const enum API_TYPE {
  ASSISTANT = 'assistant',
  FLOW = 'flow'
}

const NoLoginLink = ({ type, noLogin = false }) => {
  const [isCopied, setIsCopied] = useState<Boolean>(false);
  const { t } = useTranslation()
  const { id } = useParams()

  const copyToClipboard = (code: string) => {
    setIsCopied(true);
    copyText(code).then(() => {
      setTimeout(() => {
        setIsCopied(false);
      }, 2000);
    })
  }

  const [embed, setEmbed] = useState(false)
  const url = useMemo(() => {
    const loginUrl = `${location.origin}/chat/${type === API_TYPE.ASSISTANT ? 'assistant' : 'skill'}/auth/${id}`
    const noLoginUrl = `${location.origin}/chat/${type === API_TYPE.ASSISTANT ? 'assistant/' : ''}${id}`
    return noLogin ? noLoginUrl : loginUrl;
  }, [type, noLogin])

  const embedCode = useMemo(() => {
    if (embed) return `<script
  src="${location.origin}/iframe.js"
  id="chatbot-iframe-script"
  data-bot-src="${url}"
  data-drag="true"
  data-open-icon="${location.origin}/user.png"
  data-close-icon="${location.origin}/logo-small-dark.png"
  defer
></script>
<script>console.log("chat ready")</script>
`

    return `<iframe
  src="${url}"
  style="width: 100%; height: 100%; min-height: 700px"
  frameborder="0"
  allow="fullscreen;clipboard-write">
</iframe>`
  }, [embed, url])

  return (
    <section className='pb-20 max-w-[1600px]'>
      <Alert className='mb-4'>
        <Info className="h-4 w-4" />
        <AlertDescription className='mt-0.5'>
          {noLogin
            ? t('api.noLoginLinkDescription')
            : t('api.loginLinkDescription')}
        </AlertDescription>
      </Alert>

      <h3 className="text-lg font-bold mt-8 mb-2">{t('api.publishAsStandalonePage')}</h3>
      <Card className='mb-4'>
        <CardHeader className='pt-2 pb-0'>
          <CardTitle className='flex justify-between items-center'>
            <p>{t('api.copyLinkToBrowser')}</p>
            <div>
              <button
                className="flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                onClick={() => copyToClipboard(url)}
              >
                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
              </button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <SyntaxHighlighter
            className="w-full overflow-auto custom-scroll"
            language={'javascript'}
            style={oneDark}
          >
            {url}
          </SyntaxHighlighter>
        </CardContent>
      </Card>

      <h3 className="text-lg font-bold mt-8 mb-2">{t('api.embedIntoWebsite')}</h3>
      <div className='flex gap-2 mb-4'>
        <Card className={`w-1/2 dark:bg-[#111] cursor-pointer border-2 ${embed ? '' : 'border-primary hover:border-primary dark:hover:border-primary'}`} onClick={() => setEmbed(false)}>
          <CardHeader className='pt-2 pb-0'>
            <CardTitle>{t('api.styleOne')}</CardTitle>
          </CardHeader>
          <CardContent>
            <BorwserSkeleton />
          </CardContent>
        </Card>
        <Card className={`w-1/2 dark:bg-[#111] cursor-pointer border-2 ${embed ? 'border-primary hover:border-primary dark:hover:border-primary' : ''}`} onClick={() => setEmbed(true)}>
          <CardHeader className='pt-2 pb-0'>
            <CardTitle>{t('api.styleTwo')}</CardTitle>
          </CardHeader>
          <CardContent>
            <BorwserSkeleton size='small' />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className='pt-2 pb-0'>
          <CardTitle className='flex justify-between items-center'>
            <p>{t('api.embedCodeDescription')}</p>
            <div>
              <button
                className="flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                onClick={() => copyToClipboard(embedCode)}
              >
                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
              </button>
            </div>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <SyntaxHighlighter
            className="w-full overflow-auto custom-scroll"
            language={'javascript'}
            style={oneDark}
          >
            {embedCode}
          </SyntaxHighlighter>
        </CardContent>
      </Card>
    </section>
  );
};

export default NoLoginLink;
