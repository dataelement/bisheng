import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/bs-ui/accordion";
import { Badge } from "@/components/bs-ui/badge";
import { Button } from "@/components/bs-ui/button";
import { Calendar } from "@/components/bs-ui/calendar";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/bs-ui/card";
import { Checkbox } from "@/components/bs-ui/checkBox";
import { SearchInput, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Slider } from "@/components/bs-ui/slider";
import { Switch } from "@/components/bs-ui/switch";
import { Table, TableBody, TableCaption, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useTranslation } from "react-i18next"; // Import useTranslation

const invoices = [
    {
        invoice: "INV001",
        paymentStatus: "Paid",
        totalAmount: "$250.00",
        paymentMethod: "Credit Card",
    },
    {
        invoice: "INV002",
        paymentStatus: "Pending",
        totalAmount: "$150.00",
        paymentMethod: "PayPal",
    },
    {
        invoice: "INV003",
        paymentStatus: "Unpaid",
        totalAmount: "$350.00",
        paymentMethod: "Bank Transfer",
    },
]

export default function Example(params) {
    const { t } = useTranslation(); // Initialize translation hook

    return <div className="h-[calc(100vh-220px)] overflow-y-auto py-10 pl-2 pr-10">
        <Label className="mt-10">{t('example.buttons')}</Label>
        <div className="flex gap-2 mb-6">
            <Button variant="default">{t('example.button')}</Button>
            <Button variant="destructive">{t('example.button')}</Button>
            <Button variant="outline">{t('example.button')}</Button>
            <Button variant="secondary">{t('example.button')}</Button>
            <Button variant="ghost">{t('example.button')}</Button>
            <Button variant="link">{t('example.button')}</Button>
        </div>
        <Label>{t('example.badges')}</Label>
        <div className="flex gap-2 mb-6">
            <Badge >{t('example.badge')}</Badge>
            <Badge variant="secondary">{t('example.badge')}</Badge>
            <Badge variant="outline">{t('example.badge')}</Badge>
            <Badge variant="destructive">{t('example.badge')}</Badge>
        </div>
        <Label>{t('example.inputs')}</Label>
        <div className="flex flex-col gap-2 mb-6">
            <SearchInput placeholder={t('example.search')}></SearchInput>
            <p></p>
            <Textarea placeholder={t('example.content')} value={''}></Textarea>
        </div>
        <Label>{t('example.dropdown')}</Label>
        <div className="flex flex-col gap-2 mb-6">
            <Select>
                <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder={t('example.selectAFruit')} />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectLabel>{t('example.fruits')}</SelectLabel>
                        <SelectItem value="apple">{t('example.apple')}</SelectItem>
                        <SelectItem value="banana">{t('example.banana')}</SelectItem>
                        <SelectItem value="blueberry">{t('example.blueberry')}</SelectItem>
                        <SelectItem value="grapes">{t('example.grapes')}</SelectItem>
                        <SelectItem value="pineapple">{t('example.pineapple')}</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
        <Label>{t('example.slider')}</Label>
        <div className="flex flex-col gap-2 mb-6">
            <Slider
                defaultValue={[50]}
                max={100}
                step={1}
                className="w-[60%]"
            />
        </div>
        <Label>Switch{t('example.Switch')}</Label>
        <div className="flex flex-col gap-2 mb-6">
            <Switch id="airplane-mode" className="w-11" />
        </div>
        <Label>{t('example.checkboxRadio')}</Label>
        <div className="flex gap-2 mb-6">
            <Checkbox id="terms" />
            <RadioGroup defaultValue="one" >
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="default" id="r1" />
                    <Label htmlFor="r1">{t('example.default')}</Label>
                </div>
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="one" id="r2" />
                    <Label htmlFor="r2">{t('example.one')}</Label>
                </div>
            </RadioGroup>
        </div>
        <Label>{t('example.tablePagination')}</Label>
        <div className="flex flex-col gap-2 mb-6">
            <Table>
                <TableCaption>{t('example.invoiceListCaption')}</TableCaption>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[100px]">{t('example.invoice')}</TableHead>
                        <TableHead>{t('example.status')}</TableHead>
                        <TableHead>{t('example.method')}</TableHead>
                        <TableHead className="text-right">{t('example.amount')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {invoices.map((invoice) => (
                        <TableRow key={invoice.invoice}>
                            <TableCell className="font-medium">{invoice.invoice}</TableCell>
                            <TableCell>{invoice.paymentStatus}</TableCell>
                            <TableCell>{invoice.paymentMethod}</TableCell>
                            <TableCell className="text-right">{invoice.totalAmount}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
                <TableFooter>
                    <TableRow>
                        <TableCell colSpan={3}>{t('example.total')}</TableCell>
                        <TableCell className="text-right">$2,500.00</TableCell>
                    </TableRow>
                </TableFooter>
            </Table>
            <AutoPagination page={1} pageSize={10} total={100} />
        </div>
        <Label>{t('example.calendar')}</Label>
        <div className="flex gap-2 mb-6">
            <Calendar
                mode="single"
            />
        </div>
        <Label>{t('example.card')}</Label>
        <div className="flex gap-2 mb-6">
            <Card className="w-[350px]">
                <CardHeader>
                    <CardTitle>{t('example.createProject')}</CardTitle>
                    <CardDescription>{t('example.deployProjectDescription')}</CardDescription>
                </CardHeader>
                <CardContent>
                    {t('example.content')}
                </CardContent>
                <CardFooter className="flex justify-between">
                    <Button variant="outline">{t('example.cancel')}</Button>
                    <Button>{t('example.deploy')}</Button>
                </CardFooter>
            </Card>
        </div>
        <Label>{t('example.accordion')}</Label>
        <div className="flex gap-2 mb-6">
            <Accordion type="single" collapsible className="w-full">
                <AccordionItem value="item-1">
                    <AccordionTrigger>{t('example.isItAccessible')}</AccordionTrigger>
                    <AccordionContent>
                        {t('example.accordionAnswer1')}
                    </AccordionContent>
                </AccordionItem>
                <AccordionItem value="item-2">
                    <AccordionTrigger>{t('example.isItStyled')}</AccordionTrigger>
                    <AccordionContent>
                        {t('example.accordionAnswer2')}
                    </AccordionContent>
                </AccordionItem>
                <AccordionItem value="item-3">
                    <AccordionTrigger>{t('example.isItAnimated')}</AccordionTrigger>
                    <AccordionContent>
                        {t('example.accordionAnswer3')}
                    </AccordionContent>
                </AccordionItem>
            </Accordion>
        </div>
    </div>
};