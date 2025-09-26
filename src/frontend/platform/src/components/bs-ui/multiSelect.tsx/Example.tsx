"use client"

import { useState } from "react"
import { MultiSelect, type Option } from "./index"

const mockOptions: Option[] = [
    { label: "毕昇", value: "bisheng" },
    { label: "CHATGPT", value: "openai" },
    { label: "DEEPSEEK", value: "deepseek" },
    { label: "GPT-4", value: "gpt4" },
    { label: "LLM", value: "llm" },
    { label: "LLAMA", value: "llama" },
    { label: "LLAMA2", value: "llama2" },
    { label: "LLAMA3", value: "llama3" }
]

const mockDatabase: Record<string, Option> = {
    "user-123": { label: "张三 (User)", value: "user-123" },
    "user-456": { label: "李四 (Admin)", value: "user-456" },
    "user-789": { label: "王五 (Manager)", value: "user-789" },
    "dept-001": { label: "技术部", value: "dept-001" },
    "dept-002": { label: "产品部", value: "dept-002" },
    "dept-003": { label: "设计部", value: "dept-003" },
}

export default function MultiSelectDemo() {
    const [selectedFrameworks, setSelectedFrameworks] = useState<string[]>(["react", "nextjs"])
    const [singleValue, setSingleValue] = useState<string[]>([])
    const [searchResults, setSearchResults] = useState<Option[]>(mockOptions)
    const [loading, setLoading] = useState(false)

    const [selectedUsers, setSelectedUsers] = useState<string[]>(["user-123", "user-456", "dept-001"])

    const handleSearch = async (query: string) => {
        setLoading(true)
        // Simulate API call
        setTimeout(() => {
            const filtered = mockOptions.filter((option) => option.label.toLowerCase().includes(query.toLowerCase()))
            setSearchResults(filtered)
            setLoading(false)
        }, 500)
    }

    const handleFetchByIds = async (ids: string[]): Promise<Option[]> => {
        console.log("[v0] Fetching options for IDs:", ids)

        // Simulate API delay
        await new Promise((resolve) => setTimeout(resolve, 1000))

        const results: Option[] = []
        ids.forEach((id) => {
            const option = mockDatabase[id]
            if (option) {
                results.push(option)
            } else {
                // Return error option for unknown IDs
                results.push({
                    value: id,
                    label: `Unknown (${id})`,
                    error: true,
                })
            }
        })

        console.log("[v0] Fetched options:", results)
        return results
    }

    return (
        <div className="container mx-auto p-8 space-y-8">
            <div className="space-y-2">
                <h1 className="text-3xl font-bold">Multi-Select Component Demo</h1>
                <p className="text-muted-foreground">
                    A redesigned multi-select component with improved accessibility, performance, and maintainability.
                </p>
            </div>

            <div className="grid gap-8 md:grid-cols-2">
                <div className="space-y-4">
                    <div>
                        <h2 className="text-xl font-semibold mb-2">Multi-Select (Controlled)</h2>
                        <MultiSelect
                            options={mockOptions}
                            value={selectedFrameworks}
                            onValueChange={setSelectedFrameworks}
                            placeholder="Select frameworks..."
                            searchPlaceholder="Search frameworks..."
                            multiple={true}
                            searchable={true}
                            clearable={true}
                            lockedValues={["react"]} // React is locked and cannot be removed
                            maxDisplayed={2}
                        />
                        <p className="text-sm text-muted-foreground mt-2">Selected: {selectedFrameworks.join(", ") || "None"}</p>
                    </div>

                    <div>
                        <h2 className="text-xl font-semibold mb-2">Single Select</h2>
                        <MultiSelect
                            options={mockOptions}
                            value={singleValue}
                            onValueChange={setSingleValue}
                            placeholder="Select a framework..."
                            multiple={false}
                            searchable={true}
                            clearable={true}
                        />
                        <p className="text-sm text-muted-foreground mt-2">Selected: {singleValue[0] || "None"}</p>
                    </div>

                    <div>
                        <h2 className="text-xl font-semibold mb-2">With External Search</h2>
                        <MultiSelect
                            options={searchResults}
                            placeholder="Search and select..."
                            onSearch={handleSearch}
                            loading={loading}
                            searchable={true}
                            multiple={true}
                        />
                    </div>

                    <div>
                        <h2 className="text-xl font-semibold mb-2">With FetchByIds (回显场景)</h2>
                        <MultiSelect
                            options={[]} // No initial options
                            value={selectedUsers}
                            onValueChange={setSelectedUsers}
                            onFetchByIds={handleFetchByIds}
                            placeholder="Select users/departments..."
                            searchPlaceholder="Search users..."
                            multiple={true}
                            searchable={true}
                            clearable={true}
                            maxDisplayed={2}
                        />
                        <p className="text-sm text-muted-foreground mt-2">Selected: {selectedUsers.join(", ") || "None"}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                            这个示例演示了回显场景：组件初始化时只有ID值，通过onFetchByIds获取对应的名称显示
                        </p>
                    </div>
                </div>

                <div className="space-y-4">
                    <div>
                        <h2 className="text-xl font-semibold mb-2">Error State</h2>
                        <MultiSelect
                            options={mockOptions}
                            placeholder="This has an error..."
                            error={true}
                            errorMessage="Please select at least one option"
                            multiple={true}
                        />
                    </div>

                    <div>
                        <h2 className="text-xl font-semibold mb-2">Disabled</h2>
                        <MultiSelect
                            options={mockOptions}
                            defaultValue={["react", "vue"]}
                            placeholder="Disabled select..."
                            disabled={true}
                            multiple={true}
                        />
                    </div>

                    <div>
                        <h2 className="text-xl font-semibold mb-2">Not Searchable</h2>
                        <MultiSelect
                            options={mockOptions.slice(0, 5)}
                            placeholder="Select options..."
                            searchable={false}
                            multiple={true}
                        />
                    </div>

                    <div>
                        <h2 className="text-xl font-semibold mb-2">Custom Styling</h2>
                        <MultiSelect
                            options={mockOptions}
                            placeholder="Custom styled..."
                            className="border-2 border-blue-200"
                            triggerClassName="bg-blue-50"
                            multiple={true}
                        />
                    </div>
                </div>
            </div>

            <div className="space-y-2">
                <h2 className="text-xl font-semibold">Key Improvements</h2>
                <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                    <li>
                        <strong>Type Safety:</strong> Proper TypeScript interfaces and generics
                    </li>
                    <li>
                        <strong>Accessibility:</strong> ARIA attributes, keyboard navigation, screen reader support
                    </li>
                    <li>
                        <strong>Performance:</strong> React.memo, useMemo, useCallback for optimization
                    </li>
                    <li>
                        <strong>Maintainability:</strong> Custom hooks, separated concerns, clean component structure
                    </li>
                    <li>
                        <strong>Flexibility:</strong> Controlled/uncontrolled modes, extensive customization options
                    </li>
                    <li>
                        <strong>User Experience:</strong> Better loading states, error handling, visual feedback
                    </li>
                    <li>
                        <strong>FetchByIds:</strong> Support for fetching option names by IDs for echo scenarios
                    </li>
                </ul>
            </div>
        </div>
    )
}
