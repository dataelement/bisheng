import { Button, Input } from '@bisheng/ui';


import { Dialog,DialogContent,DialogFooter,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";
import { Select,SelectContent,SelectItem,SelectTrigger,SelectValue } from "@/components/bs-ui/select";
import { Checkbox,RadioGroup,Radio as RadioGroupItem } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import type { DimensionItem,MetricFormat } from "./DimensionBlock";
interface MetricFormatDialogProps {formatDialogOpen:boolean;setFormatDialogOpen:(open:boolean)=>void;editingMetric:DimensionItem|null;setEditingMetric:React.Dispatch<React.SetStateAction<DimensionItem|null>>;localFormat:MetricFormat|null;setLocalFormat:React.Dispatch<React.SetStateAction<MetricFormat|null>>;onFormatChange?:(id:string,format:MetricFormat)=>void}
export function MetricFormatDialog({formatDialogOpen,setFormatDialogOpen,editingMetric,setEditingMetric,localFormat,setLocalFormat,onFormatChange}:MetricFormatDialogProps){const {t}=useTranslation("dashboard");if (!editingMetric || !localFormat) return null;return (        <Dialog
          open={formatDialogOpen}
          onOpenChange={(open) => {
            setFormatDialogOpen(open)
            if (!open) {
              setEditingMetric(null)
              setLocalFormat(null)
            }
          }}
        >
          <DialogContent className="sm:max-w-[520px]">
            <DialogHeader>
              <DialogTitle>{t('dimensionBlock.dialog.formatTitle')}</DialogTitle>
            </DialogHeader>
            <div className="space-y-6 py-4">
              <div>
                <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.formatType')}</div>
                <RadioGroup
                  value={localFormat.type}
                  onValueChange={(value) => {
                    const newType = value as MetricFormat["type"];
                    let newUnit = localFormat.unit;
                    let newThousandSeparator = localFormat.thousandSeparator;
                    if (newType === 'storage') {
                      newUnit = 'B';
                    } else if (newType === 'duration') {
                      newUnit = 'ms';
                    } else if (newType === 'percent') {
                      newUnit = undefined;
                      newThousandSeparator = false;
                    } else {
                      newUnit = localFormat.unit || '';
                    }


                    const newDecimalPlaces = newType === 'number' ? 0 : 2;

                    setLocalFormat({
                      ...localFormat,
                      type: newType,
                      unit: newUnit,
                      thousandSeparator: newThousandSeparator,
                      decimalPlaces: newDecimalPlaces
                    })
                  }}
                  className="flex gap-6"
                >
                  {[
                    { label: t('dimensionBlock.dialog.formatTypes.number'), value: 'number' },
                    { label: t('dimensionBlock.dialog.formatTypes.percent'), value: 'percent' },
                    { label: t('dimensionBlock.dialog.formatTypes.duration'), value: 'duration' },
                    { label: t('dimensionBlock.dialog.formatTypes.storage'), value: 'storage' }
                  ].map(item => (
                    <div key={item.value} className="flex items-center space-x-2">
                      <RadioGroupItem value={item.value} id={`format-${item.value}`} />
                      <Label htmlFor={`format-${item.value}`} className="text-sm cursor-pointer">
                        {item.label}
                      </Label>
                    </div>
                  ))}
                </RadioGroup>
              </div>


              <div>
                <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.decimalPlaces')}</div>
                <Input type="number" min={0} max={5} step={1} value={localFormat.decimalPlaces} onInput={(e) => {
                    const input = e.target as HTMLInputElement;
                    const val = input.value;

                    if (val === '') {
                      setLocalFormat({ ...localFormat, decimalPlaces: undefined })
                    } else {
                      const numVal = Number(val);

                      if (numVal > 5) {
                        input.value = '5';
                        setLocalFormat({ ...localFormat, decimalPlaces: 5 })
                      } else if (numVal < 0) {
                        input.value = '0';
                        setLocalFormat({ ...localFormat, decimalPlaces: 0 })
                      } else {
                        setLocalFormat({ ...localFormat, decimalPlaces: numVal })
                      }
                    }
                  }} onBlur={(e) => {
                    const val = e.target.value;
                    if (val === '' || isNaN(Number(val))) {
                      const defaultDecimal = localFormat.type === 'number' ? 0 : 2;
                      setLocalFormat({ ...localFormat, decimalPlaces: defaultDecimal })
                    }
                  }} className={"w-full"} />
              </div>


              {localFormat.type !== 'percent' && (
                <>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.unit')}</div>
                      <Select
                        value={localFormat.unit ||
                          (localFormat.type === 'storage' ? 'B' :
                            localFormat.type === 'duration' ? 'ms' :
                              'none')}
                        onValueChange={(value) => {
                          const unitVal = value === "none" ? "" : value;
                          setLocalFormat({ ...localFormat, unit: unitVal })
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={t('dimensionBlock.dialog.selectUnit')} />
                        </SelectTrigger>
                        <SelectContent>
                          {/* Select Items Logic */}
                          {localFormat.type === 'number' && (
                            <>
                              <SelectItem value="none">{t('dimensionBlock.dialog.none')}</SelectItem>
                              <SelectItem value="Thousand">Thousand (K)</SelectItem>
                              <SelectItem value="Million">Million (M)</SelectItem>
                              <SelectItem value="Billion">Billion (B)</SelectItem>
                            </>
                          )}
                          {localFormat.type === 'duration' && (
                            <>
                              <SelectItem value="ms">ms</SelectItem>
                              <SelectItem value="s">s</SelectItem>
                              <SelectItem value="min">min</SelectItem>
                              <SelectItem value="hour">hour</SelectItem>
                            </>
                          )}
                          {localFormat.type === 'storage' && (
                            <>
                              <SelectItem value="B">B</SelectItem>
                              <SelectItem value="KB">KB</SelectItem>
                              <SelectItem value="MB">MB</SelectItem>
                              <SelectItem value="GB">GB</SelectItem>
                              <SelectItem value="TB">TB</SelectItem>
                            </>
                          )}
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.suffix')}</div>
                      <Input placeholder={t('dimensionBlock.dialog.enterSuffix')} value={localFormat.suffix || ""} onChange={(e) =>
                          setLocalFormat({ ...localFormat, suffix: e.target.value })
                        } className={"w-full"} />
                    </div>
                  </div>


                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={localFormat.thousandSeparator}
                      onCheckedChange={(checked) =>
                        setLocalFormat({
                          ...localFormat,
                          thousandSeparator: checked as boolean
                        })
                      }
                      id="thousand-separator"
                    />
                    <label htmlFor="thousand-separator" className="text-sm cursor-pointer">
                      {t('dimensionBlock.dialog.thousandSeparator')}
                    </label>
                  </div>
                </>
              )}


              {localFormat.type === 'percent' && (
                <div>
                  <div className="text-sm font-medium mb-2">{t('dimensionBlock.dialog.suffix')}</div>
                  <Input placeholder={t('dimensionBlock.dialog.enterSuffix')} value={localFormat.suffix || ""} onChange={(e) =>
                      setLocalFormat({ ...localFormat, suffix: e.target.value })
                    } className={"w-full"} />
                </div>
              )}


              <div className="text-sm text-muted-foreground">
                {t('dimensionBlock.dialog.example')}: {
                  localFormat.type === 'percent' ? '99%' :
                    localFormat.type === 'duration' ? '2000000' :
                      localFormat.type === 'storage' ? '2000000' : '20000'
                }
              </div>

            </div>

            {/* Footer */}
            <DialogFooter>
              <Button variant="outlined" onClick={() => {
                setFormatDialogOpen(false)
                setEditingMetric(null)
                setLocalFormat(null)
              }} color="default">
                {t('chartSelector.buttons.cancel')}
              </Button>
              <Button onClick={() => {
                if (!editingMetric || !localFormat) return
                const formatToSave: MetricFormat = {
                  type: localFormat.type,
                  decimalPlaces: localFormat.decimalPlaces,
                  thousandSeparator: localFormat.type === 'percent' ? false : localFormat.thousandSeparator,
                  unit: localFormat.type === 'percent' ? undefined : (localFormat.unit === "" ? undefined : localFormat.unit),
                  suffix: localFormat.suffix === "" ? undefined : localFormat.suffix
                }
                onFormatChange?.(editingMetric.id, formatToSave)
                setFormatDialogOpen(false)
                setEditingMetric(null)
                setLocalFormat(null)
              }}>
                {t('chartSelector.buttons.save')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>);}
