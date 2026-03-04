import type { ReactNode } from 'react';
import { useGetBsConfig } from '~/data-provider';
import { Constants } from '~/data-provider/data-provider/src';
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
  const conversation_starters = bsConfig?.conversationStarters ?? [];

  return (
    <div className={`relative ${!isNew ? 'h-full' : ''}`}>
      <div className="absolute left-0 right-0">{Header != null ? Header : null}</div>
      <div className="flex h-full flex-col items-center justify-center">
        <div className="flex items-center gap-4">
          {bsConfig?.assistantIcon?.image && (
            <img className="overflow w-[52px]" src={__APP_ENV__.BASE_URL + bsConfig.assistantIcon.image} />
          )}
          <h2 className="max-w-[75vh] px-12 text-center text-lg font-medium dark:text-white md:px-0 md:text-2xl">
            {bsConfig?.welcomeMessage}
          </h2>
        </div>
        <div className="max-w-lg text-center mt-4 text-sm font-normal text-gray-500">
          {bsConfig?.functionDescription}
        </div>

        {/* Conversation starters */}
        <div className="mt-8 flex flex-wrap justify-center gap-3 px-4">
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

        {/* Mode switch for Lingsi */}
        {lingsiEntry && (
          <div className="mx-auto mb-6 mt-2">
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
      </div>
    </div>
  );
}
