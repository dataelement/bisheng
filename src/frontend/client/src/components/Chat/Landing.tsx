import { useState, type ReactNode } from 'react';
import { useSearchParams } from "react-router-dom";
import { useLocalize } from '~/hooks';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { Constants } from '~/types/chat';
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
  const [searchParams] = useSearchParams();
  const defaultCategory = searchParams.get('category') || 'favorites';

  const [activeCategory, setActiveCategory] = useState<string>(defaultCategory)

  // Conversation starters from bsConfig
  const conversation_starters = ((bsConfig as { conversationStarters?: string[] } | undefined)?.conversationStarters) ?? [];

  return (
    <div className={`relative ${!isNew ? 'h-full' : ''}`}>
      <div className="absolute left-0 right-0">{Header != null ? Header : null}</div>
      <div className="flex h-full flex-col items-center justify-center touch-mobile:justify-start touch-mobile:pt-2 touch-mobile:pb-4 px-4">
        {/* Hero: stack vertically on 576 稿 */}
        <div className="flex flex-col touch-mobile:flex-col items-center gap-3 touch-mobile:gap-3 touch-desktop:flex-row touch-desktop:gap-4">
          {bsConfig?.assistantIcon?.image && (
            <img
              className="overflow-hidden touch-mobile:w-14 touch-mobile:h-14 w-[52px] h-[52px] object-contain shrink-0"
              src={__APP_ENV__.BASE_URL + bsConfig.assistantIcon.image}
              alt=""
            />
          )}
          <h2 className="max-w-[75vh] touch-mobile:max-w-full text-center text-xl touch-mobile:font-semibold touch-mobile:text-[#1d2129] touch-mobile:leading-snug font-medium dark:text-white touch-desktop:text-2xl px-0">
            {bsConfig?.welcomeMessage}
          </h2>
        </div>
        <div className="max-w-lg touch-mobile:max-w-full text-center mt-3 touch-mobile:mt-3 text-sm touch-mobile:text-[13px] font-normal text-gray-500 touch-mobile:text-[#4e5969] leading-relaxed">
          {bsConfig?.functionDescription}
        </div>

        {/* Mode switch — above starters to match 576 设计稿 */}
        {lingsiEntry && (
          <div className="w-full max-w-md touch-mobile:max-w-full mx-auto mt-5 touch-mobile:mt-5 px-0">
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
        <div className="mt-6 touch-mobile:mt-5 w-full max-w-2xl flex flex-wrap justify-center gap-2 touch-mobile:gap-2 touch-mobile:px-0">
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
