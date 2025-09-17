import { useMemo } from "react";
import { emitAreaTextEvent, EVENT_TYPE } from "../useAreaText"

export default function GuideWord({ data }) {

    const randomItems = useMemo(() => {
        if (data.length < 3) {
            return data; // 如果数据小于3个，直接返回
        }

        // 随机选取三个元素
        const randomIndices = [];
        while (randomIndices.length < 3) {
            const randIndex = Math.floor(Math.random() * data.length);
            if (!randomIndices.includes(randIndex)) {
                randomIndices.push(randIndex);
            }
        }

        return randomIndices.map(index => data[index]);
    }, [data]); // 依赖数组是 data，只有 data 改变时才会重新计算

    return <div className="space-y-2 mt-2 pl-12">
        {
            randomItems.map(word =>
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
