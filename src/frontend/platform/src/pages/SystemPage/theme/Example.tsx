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

    return <div className="h-[calc(100vh-220px)] overflow-y-auto py-10 pl-2 pr-10">
        <Label className="mt-10">按钮</Label>
        <div className="flex gap-2 mb-6">
            <Button variant="default">Button</Button>
            <Button variant="destructive">Button</Button>
            <Button variant="outline">Button</Button>
            <Button variant="secondary">Button</Button>
            <Button variant="ghost">Button</Button>
            <Button variant="link">Button</Button>
        </div>
        <Label>徽章</Label>
        <div className="flex gap-2 mb-6">
            <Badge >Badge</Badge>
            <Badge variant="secondary">Badge</Badge>
            <Badge variant="outline">Badge</Badge>
            <Badge variant="destructive">Badge</Badge>
        </div>
        <Label>输入框</Label>
        <div className="flex flex-col gap-2 mb-6">
            <SearchInput placeholder="Search"></SearchInput>
            <p></p>
            <Textarea placeholder="content" value={''}></Textarea>
        </div>
        <Label>下拉框</Label>
        <div className="flex flex-col gap-2 mb-6">
            <Select>
                <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Select a fruit" />
                </SelectTrigger>
                <SelectContent>
                    <SelectGroup>
                        <SelectLabel>Fruits</SelectLabel>
                        <SelectItem value="apple">Apple</SelectItem>
                        <SelectItem value="banana">Banana</SelectItem>
                        <SelectItem value="blueberry">Blueberry</SelectItem>
                        <SelectItem value="grapes">Grapes</SelectItem>
                        <SelectItem value="pineapple">Pineapple</SelectItem>
                    </SelectGroup>
                </SelectContent>
            </Select>
        </div>
        <Label>滑块</Label>
        <div className="flex flex-col gap-2 mb-6">
            <Slider
                defaultValue={[50]}
                max={100}
                step={1}
                className="w-[60%]"
            />
        </div>
        <Label>switch</Label>
        <div className="flex flex-col gap-2 mb-6">
            <Switch id="airplane-mode" className="w-11" />
        </div>
        <Label>单选多选</Label>
        <div className="flex gap-2 mb-6">
            <Checkbox id="terms" />
            <RadioGroup defaultValue="one" >
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="default" id="r1" />
                    <Label htmlFor="r1">Default</Label>
                </div>
                <div className="flex items-center space-x-2">
                    <RadioGroupItem value="one" id="r1" />
                    <Label htmlFor="r1">one</Label>
                </div>
            </RadioGroup>
        </div>
        <Label>表格&分页</Label>
        <div className="flex flex-col gap-2 mb-6">
            <Table>
                <TableCaption>A list of your recent invoices.</TableCaption>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[100px]">Invoice</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Method</TableHead>
                        <TableHead className="text-right">Amount</TableHead>
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
                        <TableCell colSpan={3}>Total</TableCell>
                        <TableCell className="text-right">$2,500.00</TableCell>
                    </TableRow>
                </TableFooter>
            </Table>
            <AutoPagination page={1} pageSize={10} total={100} />
        </div>
        <Label>日历</Label>
        <div className="flex gap-2 mb-6">
            <Calendar
                mode="single"
            />
        </div>
        <Label>卡片</Label>
        <div className="flex gap-2 mb-6">
            <Card className="w-[350px]">
                <CardHeader>
                    <CardTitle>Create project</CardTitle>
                    <CardDescription>Deploy your new project in one-click.</CardDescription>
                </CardHeader>
                <CardContent>
                    内容
                </CardContent>
                <CardFooter className="flex justify-between">
                    <Button variant="outline">Cancel</Button>
                    <Button>Deploy</Button>
                </CardFooter>
            </Card>
        </div>
        <Label>手风琴</Label>
        <div className="flex gap-2 mb-6">
            <Accordion type="single" collapsible className="w-full">
                <AccordionItem value="item-1">
                    <AccordionTrigger>Is it accessible?</AccordionTrigger>
                    <AccordionContent>
                        Yes. It adheres to the WAI-ARIA design pattern.
                    </AccordionContent>
                </AccordionItem>
                <AccordionItem value="item-2">
                    <AccordionTrigger>Is it styled?</AccordionTrigger>
                    <AccordionContent>
                        Yes. It comes with default styles that matches the other
                        components&apos; aesthetic.
                    </AccordionContent>
                </AccordionItem>
                <AccordionItem value="item-3">
                    <AccordionTrigger>Is it animated?</AccordionTrigger>
                    <AccordionContent>
                        Yes. It's animated by default, but you can disable it if you prefer.
                    </AccordionContent>
                </AccordionItem>
            </Accordion>
        </div>
    </div>
};
