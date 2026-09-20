import { Button } from '@/components/bs-ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { usagePresetRange, type UsagePreset, type UsageRange } from './usageRange'

interface UsageRangeSelectProps {
    preset: UsagePreset
    onChange: (preset: UsagePreset, range: UsageRange) => void
}

export function UsageRangeSelect({ preset, onChange }: UsageRangeSelectProps) {
    const { t } = useTranslation()
    const [open, setOpen] = useState(false)
    return (
        <Popover open={open} onOpenChange={setOpen} modal={false}>
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    className="h-9 min-w-32 justify-between font-normal"
                    aria-label={t('dsh.usageRange')}
                >
                    {t(`dsh.range.${preset}`)}
                    <ChevronDown className="ml-2 size-4 opacity-60" />
                </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 max-w-[calc(100vw-2rem)] space-y-2 p-2">
                {(['today', '30d', 'year'] as const).map((item) => (
                    <Button
                        key={item}
                        variant="ghost"
                        className="w-full justify-start"
                        onClick={() => {
                            onChange(item, usagePresetRange(item))
                            setOpen(false)
                        }}
                    >
                        {t(`dsh.range.${item}`)}
                    </Button>
                ))}
            </PopoverContent>
        </Popover>
    )
}
