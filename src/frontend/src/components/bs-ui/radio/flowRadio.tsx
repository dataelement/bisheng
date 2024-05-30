import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { Label } from "@/components/bs-ui/label";
import { Input } from "@/components/ui/input";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function FlowRadio({limit, onChange}) {
    const { t } = useTranslation()
    const [number, setNumber] = useState(100)

    const handleChange = (value) => {
        onChange(value === 'true' ? true : false)
    }
    const handleInput = (e) => {
        setNumber(parseFloat(e.target.value))
    }

    return <div>
        <RadioGroup className="flex space-x-2 h-[20px]" defaultValue={limit ? 'true' : 'false'}
        onValueChange={(value) => handleChange(value)}>
            <div>
                <Label className="flex justify-center">
                    <RadioGroupItem className="mr-2" value="false"/>{t('system.limit')}
                </Label>
            </div>
            <div>
                <Label className="flex justify-center">
                    <RadioGroupItem className="mr-2" value="true"/>{t('system.unlimited')}
                </Label>
            </div>
            {limit && <div>
                <Label>
                    <p className="mt-[-3px]">
                        {t('system.maximum')}<Input type="number" value={number} className="inline h-5 w-[70px]" 
                        onChange={handleInput}/>{t('system.perMinute')}
                    </p>
                </Label>
            </div>}
        </RadioGroup>
    </div>
}