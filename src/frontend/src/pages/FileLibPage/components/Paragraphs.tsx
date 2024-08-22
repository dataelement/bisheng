import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import {
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle
} from "@/components/bs-ui/card"
import { SearchInput } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import MultiSelect from "@/components/bs-ui/select/multi"
import { readFileByLibDatabase } from "@/controllers/API"
import { useTable } from "@/util/hook"
import { Link } from "react-router-dom"

const Item = ({ data }) => {

    const handleDel = () => {
        bsConfirm({
            title: "提示",
            desc: "确定删除分段吗？",
            onOk: () => {
                // api
                // onDeled() 乐观更新
            }
        })
    }

    return (
        <Card className="relative w-[420px]">
            {/* 序号部分 */}
            <div className="absolute right-4 top-4 font-semibold">#1</div>
            <CardHeader>
                <CardTitle className="font-semibold">{data.fileName || "讲座实录.docx"}</CardTitle>
            </CardHeader>
            <CardContent className="pb-2">
                <p className="truncate-multiline text-sm text-muted-foreground ">
                    {data.description ||
                        "杨赤忠《从投资市场到政府管理》讲座实录 编者按：本文为杨赤忠先生2018年12月13日杨赤忠《从投资市场到政府管理》讲座实录 编者按：本文为杨赤忠先生2018年12月13日杨赤忠《从投资市场到政府管理》讲座实录 编者按：本文为杨赤忠先生2018年12月13日"} {/* 省略多余内容 */}
                </p>
            </CardContent>
            <CardFooter className="flex justify-between items-center">
                <div className="flex space-x-2">
                    <Button variant="link" className="p-0" onClick={handleDel}>
                        删除
                    </Button>
                    <Link to={`/filelib/edit/1234`}>
                        <Button variant="link" className="p-0">
                            编辑
                        </Button>
                    </Link>
                </div>
                <p className="text-xs text-muted-foreground">{data.charCount || "500个字符"}</p>
            </CardFooter>
        </Card>
    );
};

export default function Paragraphs(params) {
    const options = [{ label: '选项1', value: '1' }, { label: '选项2', value: '2' }, { label: '选项1', value: '12' }, { label: '选项2', value: '22' },
    { label: '选项1', value: '211' }, { label: '选项2', value: '212' }, { label: '选项1', value: '112' }, { label: '选项2', value: '122' }
    ]

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData, refreshData } = useTable({}, (param) =>
        readFileByLibDatabase({ ...param, id: 1046, name: param.keyword, status: 999 }).then(res => {
            return res
        })
    )

    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>}
        <div className="absolute right-0 top-[-46px] flex gap-4 items-center">
            <SearchInput placeholder='搜索相关分段' onChange={(e) => { }}></SearchInput>
            <div className="min-w-72 max-w-[400px]">
                <MultiSelect
                    className="max-w-[630px]"
                    multiple
                    scroll
                    value={[]}
                    options={options}
                    placeholder={'选择文件'}
                    searchPlaceholder=''
                    onChange={() => { }}
                ></MultiSelect>
            </div>
        </div>
        <div className="h-[calc(100vh-200px)] overflow-y-auto pb-20 bg-background-main flex flex-wrap gap-2 p-2">
            {
                datalist.map((item, index) => <Item key={index} data={item}></Item>)
            }
        </div>
        <div className="bisheng-table-footer px-6">
            <p></p>
            <div>
                <AutoPagination
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
    </div>
};
