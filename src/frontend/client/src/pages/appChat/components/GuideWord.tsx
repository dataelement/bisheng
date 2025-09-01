import { emitAreaTextEvent, EVENT_TYPE } from "../useAreaText"

export default function GuideWord({ data }) {


    return <div className="space-y-2 mt-2">
        {
            data.map(word =>
                <p
                    className="text-xs border w-fit p-3 py-1 rounded-md text-[#1f2937cc] cursor-pointer hover:bg-[#6e87ac33]"
                    onClick={() => emitAreaTextEvent({ action: EVENT_TYPE.INPUT_SUBMIT, data: word })}
                    key={word}
                >
                    {word}
                </p>
            )
        }
    </div>
};
