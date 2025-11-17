import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import { Button } from "../../../components/bs-ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../../components/bs-ui/table";
import {
  PlusCircle,
  Edit2,
  Trash2,
  Type,
  Hash,
  Clock,
  Info,
  Loader2,
} from "lucide-react";
import { Input } from "../../../components/bs-ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../../components/bs-ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../../components/bs-ui/tooltip";
import { useTranslation } from "react-i18next";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
// import { getMetadata, saveMetadata } from "../../../controllers/API"; // 假设的元数据接口

// 元数据类型定义
type MetadataType = "String" | "Number" | "Time";

// 元数据条目接口
interface MetadataItem {
  id?: string; // 自定义元数据才有id
  name: string; // 变量名
  value: string | number | Date; // 值
  type: MetadataType; // 类型
  updatedAt: string; // 修改时间
}

// 内置元数据常量
const builtInMetadata: MetadataItem[] = [
  {
    name: "document_id",
    value: "10001", // 实际值从接口获取
    type: "Number",
    updatedAt: "",
  },
  {
    name: "document_name",
    value: "产品需求文档", // 实际值从接口获取
    type: "String",
    updatedAt: "",
  },
  {
    name: "upload_time",
    value: "2024-05-20 14:30:00", // 实际值从接口获取
    type: "Time",
    updatedAt: "",
  },
  {
    name: "update_time",
    value: "2024-05-21 09:15:00", // 实际值从接口获取
    type: "Time",
    updatedAt: "",
  },
  {
    name: "uploader",
    value: "张三", // 实际值从接口获取
    type: "String",
    updatedAt: "",
  },
  {
    name: "updater",
    value: "李四", // 实际值从接口获取
    type: "Time",
    updatedAt: "",
  },
];

// 类型图标映射
const TypeIcon = ({ type }: { type: MetadataType }) => {
  switch (type) {
    case "String":
      return <Type size={16} className="text-blue-500" />;
    case "Number":
      return <Hash size={16} className="text-green-500" />;
    case "Time":
      return <Clock size={16} className="text-purple-500" />;
    default:
      return null;
  }
};

export default function MetadataDialog({
  open,
  onClose,
  documentId, // 传入当前文档ID
}: {
  open: boolean;
  onClose: () => void;
  documentId: string;
}) {
  const { t } = useTranslation("knowledge");
  const [customMetadata, setCustomMetadata] = useState<MetadataItem[]>([]);
  const [editingItem, setEditingItem] = useState<MetadataItem | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // 初始化加载元数据
  useEffect(() => {
    if (open && documentId) {
      loadMetadata();
    }
  }, [open, documentId]);

  // 加载元数据
  const loadMetadata = async () => {
    setIsLoading(true);
    try {
    //   const res = await getMetadata(documentId);
      // 按修改时间倒序排列（最新的在下面）
    //   const sorted = res.data.sort((a: MetadataItem, b: MetadataItem) => 
    //     new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime()
    //   );
    //   setCustomMetadata(sorted);
    } catch (error) {
      console.error("加载元数据失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // 新建元数据
  const handleAddMetadata = () => {
    const newItem: MetadataItem = {
      name: "",
      value: "",
      type: "String",
      updatedAt: new Date().toISOString(),
    };
    setEditingItem(newItem);
    // 添加到列表并保持排序
    setCustomMetadata([...customMetadata, newItem]);
  };

  // 编辑元数据
  const handleEdit = (item: MetadataItem) => {
    setEditingItem({ ...item });
  };

  // 删除元数据
  const handleDelete = (id: string) => {
    setCustomMetadata(customMetadata.filter(item => item.id !== id));
  };

  // 保存修改
  const handleSaveChanges = () => {
    if (editingItem) {
      const updatedItems = customMetadata.map(item => 
        item.id === editingItem.id ? { ...editingItem, updatedAt: new Date().toISOString() } : item
      );
      // 重新排序
      const sorted = updatedItems.sort((a, b) => 
        new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime()
      );
      setCustomMetadata(sorted);
      setEditingItem(null);
    }
  };

  // 提交保存所有元数据
  const handleSubmit = async () => {
    setIsSaving(true);
    try {
    //   await captureAndAlertRequestErrorHoc(
    //     saveMetadata(documentId, customMetadata)
    //   );
      onClose(); // 保存成功后关闭弹窗
    } finally {
      setIsSaving(false);
    }
  };

  // 处理输入变化
  const handleInputChange = (field: keyof MetadataItem, value: string) => {
    if (editingItem) {
      setEditingItem({
        ...editingItem,
        [field]: value,
      });
    }
  };

  // 处理类型变化
  const handleTypeChange = (type: MetadataType) => {
    if (editingItem) {
      setEditingItem({
        ...editingItem,
        type,
        // 类型切换时重置值
        value: type === "Number" ? 0 : type === "Time" ? new Date().toISOString() : "",
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[800px] max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl">{t("【元数据】")}</DialogTitle>
        </DialogHeader>

        {/* 新建元数据按钮 */}
        <div className="flex justify-end mb-4">
          <Button onClick={handleAddMetadata} className="gap-1">
            <PlusCircle size={16} />
            {t("【 + 新建元数据】")}
          </Button>
        </div>

        {/* 自定义元数据列表 */}
        <div className="mb-8">
          <h3 className="text-lg font-medium mb-3">{t("元数据条目")}</h3>
          {isLoading ? (
            <div className="flex justify-center py-6">
              <Loader2 className="animate-spin" size={24} />
            </div>
          ) : customMetadata.length === 0 ? (
            <div className="text-center text-gray-500 py-6">
              {t("暂无自定义元数据")}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[80px]">{t("类型")}</TableHead>
                  <TableHead>{t("值")}</TableHead>
                  <TableHead>{t("变量名")}</TableHead>
                  <TableHead className="w-[120px]">{t("修改时间")}</TableHead>
                  <TableHead className="w-[80px] text-right">{t("操作")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {customMetadata.map((item) => (
                  <TableRow key={item.id || item.name}>
                    <TableCell>
                      <div className="flex items-center">
                        <TypeIcon type={item.type} />
                        <span className="ml-2 capitalize">{item.type}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      {editingItem?.id === item.id || (!item.id && editingItem?.name === item.name) ? (
                        <Input
                          value={editingItem?.value?.toString() || ""}
                          onChange={(e) => handleInputChange("value", e.target.value)}
                          type={item.type === "Number" ? "number" : item.type === "Time" ? "datetime-local" : "text"}
                        />
                      ) : (
                        item.value.toString()
                      )}
                    </TableCell>
                    <TableCell>
                      {editingItem?.id === item.id || (!item.id && editingItem?.name === item.name) ? (
                        <Input
                          value={editingItem?.name || ""}
                          onChange={(e) => handleInputChange("name", e.target.value)}
                        />
                      ) : (
                        item.name
                      )}
                    </TableCell>
                    <TableCell>
                      {new Date(item.updatedAt).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right">
                      {editingItem?.id === item.id || (!item.id && editingItem?.name === item.name) ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleSaveChanges}
                          className="h-8"
                        >
                          {t("保存")}
                        </Button>
                      ) : (
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleEdit(item)}
                            className="h-8 w-8"
                          >
                            <Edit2 size={16} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDelete(item.id!)}
                            className="h-8 w-8 text-red-500"
                          >
                            <Trash2 size={16} />
                          </Button>
                        </>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>

        {/* 内置元数据列表 */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h3 className="text-lg font-medium">{t("【内置元数据】")}</h3>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info size={16} className="text-gray-400 cursor-help" />
                </TooltipTrigger>
                <TooltipContent>
                  <p>{t("内置元数据是系统预定义的元数据")}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[80px]">{t("类型")}</TableHead>
                <TableHead>{t("值")}</TableHead>
                <TableHead>{t("变量名")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {builtInMetadata.map((item) => (
                <TableRow key={item.name}>
                  <TableCell>
                    <div className="flex items-center">
                      <TypeIcon type={item.type} />
                      <span className="ml-2 capitalize">{item.type}</span>
                    </div>
                  </TableCell>
                  <TableCell>{item.value.toString()}</TableCell>
                  <TableCell className="font-medium">{item.name}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <DialogFooter className="mt-6">
          <Button variant="outline" onClick={onClose}>
            {t("【取消】")}
          </Button>
          <Button onClick={handleSubmit} disabled={isSaving}>
            {isSaving ? (
              <>
                <Loader2 className="animate-spin mr-2" size={16} />
                {t("保存中...")}
              </>
            ) : (
              t("【保存】")
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}