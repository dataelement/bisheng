import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export const enum LimitType {
    LIMITED = 'limited',
    UNLIMITED = 'unlimited'
}

export function FlowRadio({ limit, onChange }: { limit: number; onChange: (val: number) => void }) {
    const { t } = useTranslation()
    const [status, setStatus] = useState(LimitType.UNLIMITED)
    const [limitState, setLimitState] = useState<any>(limit)
    const limitRef = useRef(0)

    const handleCommit = (type: LimitType, value: string = '0') => {
        if (value === '') return
        const valueNum = parseInt(value)
        if (valueNum < 0 || valueNum > 9999) return
        setStatus(type)
        setLimitState(value)
        onChange(Number(value))
        limitRef.current = Number(value)
    }
    useEffect(() => {
        setStatus(limit ? LimitType.LIMITED : LimitType.UNLIMITED)
        setLimitState(limit)
        limitRef.current = limit
    }, [limit])

    return <div>
        <RadioGroup className="flex space-x-2 h-[20px] items-center" value={status}
            onValueChange={(value: LimitType) => handleCommit(value, value === LimitType.LIMITED ? '10' : '0')}>
            <div>
                <Label className="flex justify-center">
                    <RadioGroupItem className="mr-2" value={LimitType.UNLIMITED} />{t('system.unlimited')}
                </Label>
            </div>
            <div>
                <Label className="flex justify-center">
                    <RadioGroupItem className="mr-2" value={LimitType.LIMITED} />{t('system.limit')}
                </Label>
            </div>
            {status === LimitType.LIMITED && <div className="mt-[-3px] flex items-center">
                <Label className="whitespace-nowrap">{t('system.maximum')}</Label>
                <Input
                    type="number"
                    value={limitState}
                    className="inline h-5 w-[70px] font-medium"
                    onChange={(e) => handleCommit(LimitType.LIMITED, e.target.value)}
                    onBlur={(e) => {
                        if (e.target.value === '') {
                            e.target.value = limitRef.current + ''
                        }
                    }}
                />
                <Label className="min-w-[100px]">{t('system.perMinute')}</Label>
            </div>}
        </RadioGroup>
    </div>
}
