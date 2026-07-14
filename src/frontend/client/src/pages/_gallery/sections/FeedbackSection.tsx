/**
 * Message feedback (点赞/点踩) gallery — DEV-ONLY.
 *
 * The single shared control `MessageFeedbackButtons` now backs every AI answer
 * surface (daily chat / 知源 / subscription docks / linsight ResultPanel / appChat
 * MessageButtons — the old appChat MessageFeedbackForm was deleted). Dislike is
 * deferred: the reason dialog must be submitted before anything persists or
 * highlights; cancel discards the dislike. The demos below persist to console.log
 * only, so the dialog interaction can be exercised without a backend.
 */
import { useState } from 'react';
import { MessageFeedbackButtons } from '~/components/Chat/MessageFeedbackButtons';
import { ComponentPage, ExampleGroup, ExampleGrid, ExampleCard } from '../components/kit';

function LoggedDemo({ liked }: { liked?: number }) {
  const [last, setLast] = useState<string>('—');
  return (
    <div className="flex items-center gap-4">
      <MessageFeedbackButtons
        liked={liked}
        onLike={(l) => setLast(`onLike(${l})`)}
        onDislikeComment={(c) => setLast(`onDislikeComment("${c}")`)}
      />
      <span className="text-caption text-muted-foreground">最近调用：{last}</span>
    </div>
  );
}

export function FeedbackSection() {
  return (
    <ComponentPage
      title="点赞 / 点踩反馈"
      eng="Message Feedback"
      description={
        <>
          <code>MessageFeedbackButtons</code> — 全部 6 类 AI 回答界面共用（首页对话 / 知源 /
          订阅 3 面板 / 灵思 / appChat）。
        </>
      }
      whenToUse={[
        <>点踩为<b>延迟提交</b>：弹窗点「提交」才落库并高亮，原因选填；「取消」= 彻底放弃点踩。</>,
        <>已点踩态再点踩 = 直接取消（<code>onLike(0)</code>），不再弹窗。</>,
        <>弹窗规格：圆角 12 / 边距 20 / 按钮 32 高 · 14px · 字重 400 · 圆角 6。</>,
      ]}
    >
      <ExampleGroup title="三种初始状态">
        <ExampleGrid cols={3}>
          <ExampleCard title="初始未评价" description="点踩先弹窗，提交后才高亮；取消不留痕">
            <LoggedDemo />
          </ExampleCard>
          <ExampleCard title="已点赞态（liked=1）" description="点踩弹窗取消后应保持点赞高亮">
            <LoggedDemo liked={1} />
          </ExampleCard>
          <ExampleCard title="已点踩态（liked=2）" description="再点踩=直接取消（onLike(0)），不弹窗">
            <LoggedDemo liked={2} />
          </ExampleCard>
        </ExampleGrid>
      </ExampleGroup>
    </ComponentPage>
  );
}
