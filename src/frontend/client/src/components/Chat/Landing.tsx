import type { ReactNode } from 'react';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { Constants } from '~/types/chat';
import { useLocalize } from '~/hooks';
import { useInterruptAudio } from '../Voice/textToSpeechStore';
import ConvoStarter from './ConvoStarter';
import SegmentSelector from './SegmentSelector';

export default function Landing({ Header, isNew, lingsi, lingsiEntry, setLingsi }: {
  Header?: ReactNode;
  isNew?: boolean;
  lingsi: boolean;
  lingsiEntry?: boolean;
  setLingsi: (val: boolean) => void;
}) {
  const { data: bsConfig } = useGetBsConfig();
  const interruptAudio = useInterruptAudio();
  const localize = useLocalize();

  // Conversation starters from bsConfig
  const conversation_starters = ((bsConfig as { conversationStarters?: string[] } | undefined)?.conversationStarters) ?? [];

  return (
    <div className={`relative ${!isNew ? 'h-full' : ''}`}>
      <div className="absolute left-0 right-0">{Header != null ? Header : null}</div>
      <div className="flex h-full flex-col items-center justify-center max-[575px]:justify-start max-[575px]:pt-2 max-[575px]:pb-4 px-4">
        {/* Hero: stack vertically on 576 稿 */}
        <div className="flex flex-col max-[575px]:flex-col items-center gap-3 max-[575px]:gap-3 md:flex-row md:gap-4">
          {bsConfig?.assistantIcon?.image && (
            <img
              className="overflow-hidden max-[575px]:w-14 max-[575px]:h-14 w-[52px] h-[52px] object-contain shrink-0"
              src={__APP_ENV__.BASE_URL + bsConfig.assistantIcon.image}
              alt=""
            />
          )}
          <h2 className="max-w-[75vh] max-[575px]:max-w-full text-center text-xl max-[575px]:font-semibold max-[575px]:text-[#1d2129] max-[575px]:leading-snug font-medium dark:text-white md:text-2xl px-0">
            {bsConfig?.welcomeMessage}
          </h2>
        </div>
        <div className="max-w-lg max-[575px]:max-w-full text-center mt-3 max-[575px]:mt-3 text-sm max-[575px]:text-[13px] font-normal text-gray-500 max-[575px]:text-[#4e5969] leading-relaxed">
          {bsConfig?.functionDescription}
        </div>

        {/* Mode switch — above starters to match 576 设计稿 */}
        {lingsiEntry && (
          <div className="w-full max-w-md max-[575px]:max-w-full mx-auto mt-5 max-[575px]:mt-5 px-0">
            <SegmentSelector
              lingsi={lingsi}
              bsConfig={bsConfig}
              onChange={(bl) => {
                setLingsi(bl);
                interruptAudio();
              }}
            />
          </div>
        )}

        {/* Conversation starters */}
        <div className="mt-6 max-[575px]:mt-5 w-full max-w-2xl flex flex-wrap justify-center gap-2 max-[575px]:gap-2 max-[575px]:px-0">
          {conversation_starters.length > 0 &&
            conversation_starters
              .slice(0, Constants.MAX_CONVO_STARTERS)
              .map((text: string, index: number) => (
                <ConvoStarter
                  key={index}
                  text={text}
                  onClick={() => {
                    // Conversation starter click is handled in parent
                    console.log('Convo starter clicked:', text);
                  }}
                />
              ))}
        </div>
      </div>
    </div>
  );
}
