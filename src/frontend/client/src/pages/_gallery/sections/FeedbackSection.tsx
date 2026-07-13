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
import { Section, Demo, DemoGrid } from '../components/kit';

function LoggedDemo({ liked }: { liked?: number }) {
    const [last, setLast] = useState<string>('—');
    return (
        <div className="flex items-center gap-4">
            <MessageFeedbackButtons
                liked={liked}
                onLike={(l) => setLast(`onLike(${l})`)}
                onDislikeComment={(c) => setLast(`onDislikeComment("${c}")`)}
            />
            <span className="text-xs text-muted-foreground">最近调用：{last}</span>
        </div>
    );
}

export function FeedbackSection() {
    return (
        <Section
            id="feedback"
            title="点赞 / 点踩反馈"
            subtitle={
                <>
                    <code>MessageFeedbackButtons</code> — 全部 6 类 AI 回答界面共用（首页对话 / 知源 /
                    订阅 3 面板 / 灵思 / appChat）。点踩为<b>延迟提交</b>：弹窗点「提交」才落库并高亮，
                    原因选填；「取消」= 彻底放弃点踩。弹窗规格：圆角 12 / 边距 20 / 按钮 32 高 · 14px ·
                    字重 400 · 圆角 6。
                </>
            }
        >
            <DemoGrid cols={3}>
                <Demo label="初始未评价" note="点踩先弹窗，提交后才高亮；取消不留痕">
                    <LoggedDemo />
                </Demo>
                <Demo label="已点赞态（liked=1）" note="点踩弹窗取消后应保持点赞高亮">
                    <LoggedDemo liked={1} />
                </Demo>
                <Demo label="已点踩态（liked=2）" note="再点踩=直接取消（onLike(0)），不弹窗">
                    <LoggedDemo liked={2} />
                </Demo>
            </DemoGrid>
        </Section>
    );
}
