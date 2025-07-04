import { useToast } from "@/components/bs-ui/toast/use-toast";
import { ArrowLeft, Key, Copy, Edit, Trash2, Plus, CalendarDays, Clock } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { Badge } from "@/components/bs-ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { Calendar } from "@/components/bs-ui/calendar";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { createApiKeyApi, getApiKeysApi, updateApiKeyApi, deleteApiKeyApi } from "@/controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { formatDate as utilFormatDate } from "@/util/utils";

interface ApiKey {
    id: number;
    key_name: string;
    api_key: string;
    is_active: boolean;
    last_used_at: string | null;
    total_uses: number;
    expires_at: string | null;
    remark: string | null;
    create_time: string;
    update_time: string;
}

export const ApiKeyPage = () => {
    const { t } = useTranslation();
    const { message } = useToast();
    const navigate = useNavigate();

    const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
    const [loading, setLoading] = useState(false);
    const [showCreateDialog, setShowCreateDialog] = useState(false);
    const [showEditDialog, setShowEditDialog] = useState(false);
    const [editingKey, setEditingKey] = useState<ApiKey | null>(null);
    const [newApiKey, setNewApiKey] = useState<string>('');

    // 表单数据
    const [formData, setFormData] = useState({
        keyName: '',
        expiresAt: '',
        remark: ''
    });

    // 日期选择器状态
    const [createExpiresDate, setCreateExpiresDate] = useState<Date | undefined>();
    const [createExpiresTime, setCreateExpiresTime] = useState('');
    const [editExpiresDate, setEditExpiresDate] = useState<Date | undefined>();
    const [editExpiresTime, setEditExpiresTime] = useState('');

    // 加载API Keys
    const loadApiKeys = async () => {
        setLoading(true);
        try {
            const response = await captureAndAlertRequestErrorHoc(getApiKeysApi());
            if (response) {
                setApiKeys(response);
            }
        } catch (error) {
            console.error('Failed to load API keys:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadApiKeys();
    }, []);

    // 创建API Key
    const handleCreateApiKey = async () => {
        if (!formData.keyName.trim()) {
            message({
                title: t('prompt'),
                variant: 'warning',
                description: [t('apiKey.keyNameRequired')]
            });
            return;
        }

        // 构建过期时间
        let expiresAtValue = undefined;
        if (createExpiresDate) {
            const timeValue = createExpiresTime || '23:59';
            const [hours, minutes] = timeValue.split(':');
            const expiresDateTime = new Date(createExpiresDate);
            expiresDateTime.setHours(parseInt(hours), parseInt(minutes), 0, 0);
            expiresAtValue = expiresDateTime.toISOString();
        }

        try {
            const response = await captureAndAlertRequestErrorHoc(
                createApiKeyApi(
                    formData.keyName,
                    expiresAtValue,
                    formData.remark || undefined
                )
            );

            if (response) {
                setNewApiKey(response.api_key);
                message({
                    title: t('prompt'),
                    variant: 'success',
                    description: [t('apiKey.createSuccess')]
                });
                setFormData({ keyName: '', expiresAt: '', remark: '' });
                setCreateExpiresDate(undefined);
                setCreateExpiresTime('');
                loadApiKeys();
            }
        } catch (error) {
            message({
                title: t('prompt'),
                variant: 'error',
                description: [t('apiKey.createFailed')]
            });
        }
    };

    // 更新API Key
    const handleUpdateApiKey = async () => {
        if (!editingKey || !formData.keyName.trim()) {
            message({
                title: t('prompt'),
                variant: 'warning',
                description: [t('apiKey.keyNameRequired')]
            });
            return;
        }

        // 构建过期时间
        let expiresAtValue = undefined;
        if (editExpiresDate) {
            const timeValue = editExpiresTime || '23:59';
            const [hours, minutes] = timeValue.split(':');
            const expiresDateTime = new Date(editExpiresDate);
            expiresDateTime.setHours(parseInt(hours), parseInt(minutes), 0, 0);
            expiresAtValue = expiresDateTime.toISOString();
        }

        try {
            await captureAndAlertRequestErrorHoc(
                updateApiKeyApi(
                    editingKey.id,
                    formData.keyName,
                    undefined,
                    expiresAtValue,
                    formData.remark || undefined
                )
            );

            message({
                title: t('prompt'),
                variant: 'success',
                description: [t('apiKey.updateSuccess')]
            });
            setShowEditDialog(false);
            setEditingKey(null);
            setFormData({ keyName: '', expiresAt: '', remark: '' });
            setEditExpiresDate(undefined);
            setEditExpiresTime('');
            loadApiKeys();
        } catch (error) {
            message({
                title: t('prompt'),
                variant: 'error',
                description: [t('apiKey.updateFailed')]
            });
        }
    };

    // 删除API Key
    const handleDeleteApiKey = (apiKey: ApiKey) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('apiKey.deleteConfirm'),
            okTxt: t('confirm'),
            onOk: async (next) => {
                try {
                    await captureAndAlertRequestErrorHoc(deleteApiKeyApi(apiKey.id));
                    message({
                        title: t('prompt'),
                        variant: 'success',
                        description: [t('apiKey.deleteSuccess')]
                    });
                    loadApiKeys();
                } catch (error) {
                    message({
                        title: t('prompt'),
                        variant: 'error',
                        description: [t('apiKey.deleteFailed')]
                    });
                }
                next();
            }
        });
    };

    // 切换API Key状态
    const handleToggleStatus = async (apiKey: ApiKey) => {
        try {
            await captureAndAlertRequestErrorHoc(
                updateApiKeyApi(apiKey.id, undefined, !apiKey.is_active)
            );
            message({
                title: t('prompt'),
                variant: 'success',
                description: [t('apiKey.statusChanged')]
            });
            loadApiKeys();
        } catch (error) {
            message({
                title: t('prompt'),
                variant: 'error',
                description: [t('apiKey.updateFailed')]
            });
        }
    };

    // 复制API Key
    const handleCopyApiKey = async (apiKey: string) => {
        if (navigator.clipboard) {
            try {
                await navigator.clipboard.writeText(apiKey);
                message({
                    title: t('prompt'),
                    variant: 'success',
                    description: [t('apiKey.copySuccess')]
                });
                return true;
            } catch {
                message({
                    title: t('prompt'),
                    variant: 'error',
                    description: [t('apiKey.copyFailed')]
                });
                return false;
            }
        } else {
            message({
                title: t('prompt'),
                variant: 'error',
                description: [t('apiKey.copyFailed')]
            });
            return false;
        }
    };

    // 打开编辑对话框
    const openEditDialog = (apiKey: ApiKey) => {
        setEditingKey(apiKey);
        setFormData({
            keyName: apiKey.key_name,
            expiresAt: apiKey.expires_at ? apiKey.expires_at.split('T')[0] : '',
            remark: apiKey.remark || ''
        });

        // 设置编辑时的日期和时间
        if (apiKey.expires_at) {
            const expiresDate = new Date(apiKey.expires_at);
            setEditExpiresDate(expiresDate);
            setEditExpiresTime(
                expiresDate.getHours().toString().padStart(2, '0') + ':' +
                expiresDate.getMinutes().toString().padStart(2, '0')
            );
        } else {
            setEditExpiresDate(undefined);
            setEditExpiresTime('');
        }

        setShowEditDialog(true);
    };

    // 格式化日期
    const formatDate = (dateString: string | null) => {
        if (!dateString) return t('apiKey.neverUsed');
        return new Date(dateString).toLocaleString();
    };

    // 检查是否过期
    const isExpired = (expiresAt: string | null) => {
        if (!expiresAt) return false;
        return new Date(expiresAt) < new Date();
    };

    // 日期时间选择器组件
    const DateTimePicker = ({
        date,
        time,
        onDateChange,
        onTimeChange,
        placeholder = "选择过期时间"
    }: {
        date: Date | undefined;
        time: string;
        onDateChange: (date: Date | undefined) => void;
        onTimeChange: (time: string) => void;
        placeholder?: string;
    }) => {
        const dateStr = date ? utilFormatDate(date, 'yyyy-MM-dd') : '';
        const displayText = date ? `${dateStr} ${time || '23:59'}` : placeholder;

        return (
            <div className="space-y-2">
                <Popover>
                    <PopoverTrigger asChild>
                        <Button
                            variant="outline"
                            className="w-full justify-start text-left font-normal bg-search-input"
                        >
                            <CalendarDays className="mr-2 h-4 w-4" />
                            <span className={!date ? "text-muted-foreground" : ""}>
                                {displayText}
                            </span>
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-0" align="start">
                        <Calendar
                            mode="single"
                            selected={date}
                            onSelect={onDateChange}
                            initialFocus
                            disabled={(date) => date < new Date(new Date().setHours(0, 0, 0, 0))}
                        />
                        {date && (
                            <div className="p-3 border-t">
                                <div className="flex items-center space-x-2">
                                    <Clock className="h-4 w-4 text-muted-foreground" />
                                    <Label htmlFor="time" className="text-sm">时间:</Label>
                                    <Input
                                        id="time"
                                        type="time"
                                        value={time}
                                        onChange={(e) => onTimeChange(e.target.value)}
                                        className="w-auto"
                                    />
                                </div>
                                <p className="text-xs text-muted-foreground mt-2">
                                    如不设置时间，默认为当天 23:59
                                </p>
                            </div>
                        )}
                    </PopoverContent>
                </Popover>
            </div>
        );
    };

    return (
        <div className="w-full h-full bg-background-dark">
            <div className="fixed z-10 sm:w-[90%] max-w-[1200px] w-full sm:h-[90%] h-full translate-x-[-50%] translate-y-[-50%] left-[50%] top-[50%] border rounded-lg shadow-xl overflow-hidden bg-background-login">
                <div className="flex items-center justify-between p-6 border-b">
                    <div className="flex items-center gap-4">
                        <Button
                            variant="outline"
                            size="icon"
                            onClick={() => navigate(-1)}
                        >
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                        <div>
                            <h1 className="text-2xl font-bold flex items-center gap-2">
                                <Key className="h-6 w-6" />
                                {t('apiKey.title')}
                            </h1>
                            <p className="text-sm text-muted-foreground mt-1">
                                {t('apiKey.description')}
                            </p>
                        </div>
                    </div>
                    <Button onClick={() => setShowCreateDialog(true)}>
                        <Plus className="h-4 w-4 mr-2" />
                        {t('apiKey.createNew')}
                    </Button>
                </div>

                <div className="p-6 h-[calc(100%-120px)] overflow-auto">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('apiKey.keyName')}</TableHead>
                                <TableHead>API Key</TableHead>
                                <TableHead>{t('apiKey.status')}</TableHead>
                                <TableHead>{t('apiKey.created')}</TableHead>
                                <TableHead>{t('apiKey.lastUsed')}</TableHead>
                                <TableHead>{t('apiKey.totalUses')}</TableHead>
                                <TableHead>{t('apiKey.expiresAt')}</TableHead>
                                <TableHead>{t('apiKey.actions')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {apiKeys.map((apiKey) => (
                                <TableRow key={apiKey.id}>
                                    <TableCell className="font-medium">
                                        {apiKey.key_name}
                                        {apiKey.remark && (
                                            <div className="text-xs text-muted-foreground mt-1">
                                                {apiKey.remark}
                                            </div>
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        <code className="text-xs bg-muted px-2 py-1 rounded">
                                            {apiKey.api_key}
                                        </code>
                                    </TableCell>
                                    <TableCell>
                                        <Badge
                                            variant={apiKey.is_active ? "default" : "secondary"}
                                            className="cursor-pointer"
                                            onClick={() => handleToggleStatus(apiKey)}
                                        >
                                            {apiKey.is_active ? t('apiKey.active') : t('apiKey.inactive')}
                                        </Badge>
                                    </TableCell>
                                    <TableCell className="text-sm">
                                        {formatDate(apiKey.create_time)}
                                    </TableCell>
                                    <TableCell className="text-sm">
                                        {formatDate(apiKey.last_used_at)}
                                    </TableCell>
                                    <TableCell>{apiKey.total_uses}</TableCell>
                                    <TableCell>
                                        {apiKey.expires_at ? (
                                            <Badge variant={isExpired(apiKey.expires_at) ? "destructive" : "outline"}>
                                                {isExpired(apiKey.expires_at) ? t('apiKey.expired') : formatDate(apiKey.expires_at)}
                                            </Badge>
                                        ) : (
                                            <Badge variant="outline">{t('apiKey.noExpiration')}</Badge>
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        <div className="flex items-center gap-2">
                                            <TooltipProvider>
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            onClick={() => openEditDialog(apiKey)}
                                                        >
                                                            <Edit className="h-3 w-3" />
                                                        </Button>
                                                    </TooltipTrigger>
                                                    <TooltipContent>
                                                        <p>{t('apiKey.edit')}</p>
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                            <TooltipProvider>
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            onClick={() => handleDeleteApiKey(apiKey)}
                                                        >
                                                            <Trash2 className="h-3 w-3" />
                                                        </Button>
                                                    </TooltipTrigger>
                                                    <TooltipContent>
                                                        <p>{t('apiKey.delete')}</p>
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                        </div>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>

                    {apiKeys.length === 0 && !loading && (
                        <div className="text-center py-12">
                            <Key className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                            <p className="text-muted-foreground">暂无API Key</p>
                        </div>
                    )}
                </div>
            </div>

            {/* 创建API Key对话框 */}
            <Dialog open={showCreateDialog} onOpenChange={(open) => {
                setShowCreateDialog(open);
                if (!open) {
                    setFormData({ keyName: '', expiresAt: '', remark: '' });
                    setCreateExpiresDate(undefined);
                    setCreateExpiresTime('');
                    setNewApiKey('');
                }
            }}>
                <DialogContent className="sm:max-w-[500px]">
                    <DialogHeader>
                        <DialogTitle>{t('apiKey.createNew')}</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4 py-4">
                        <div className="space-y-2">
                            <Label htmlFor="keyName">{t('apiKey.keyName')} *</Label>
                            <Input
                                id="keyName"
                                value={formData.keyName}
                                onChange={(e) => setFormData({ ...formData, keyName: e.target.value })}
                                placeholder={t('apiKey.keyNamePlaceholder')}
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>{t('apiKey.expiresAt')}</Label>
                            <DateTimePicker
                                date={createExpiresDate}
                                time={createExpiresTime}
                                onDateChange={setCreateExpiresDate}
                                onTimeChange={setCreateExpiresTime}
                                placeholder="选择过期时间（可选）"
                            />
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="remark">{t('apiKey.remark')}</Label>
                            <Input
                                id="remark"
                                value={formData.remark}
                                onChange={(e) => setFormData({ ...formData, remark: e.target.value })}
                                placeholder={t('apiKey.remarkPlaceholder')}
                            />
                        </div>
                        {newApiKey && (
                            <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                                <p className="text-sm text-yellow-800 mb-2">
                                    {t('apiKey.keyCreatedWarning')}
                                </p>
                                <div className="flex items-center gap-2">
                                    <code className="flex-1 text-xs bg-white px-2 py-1 rounded border">
                                        {newApiKey}
                                    </code>
                                    <Button
                                        size="sm"
                                        onClick={async () => {
                                            const success = await handleCopyApiKey(newApiKey);
                                            if (success) {
                                                setShowCreateDialog(false);
                                                setFormData({ keyName: '', expiresAt: '', remark: '' });
                                                setCreateExpiresDate(undefined);
                                                setCreateExpiresTime('');
                                                setNewApiKey('');
                                            }
                                        }}
                                    >
                                        <Copy className="h-3 w-3 mr-1" />
                                        {t('apiKey.copyAndClose')}
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => {
                            setShowCreateDialog(false);
                            setFormData({ keyName: '', expiresAt: '', remark: '' });
                            setCreateExpiresDate(undefined);
                            setCreateExpiresTime('');
                            setNewApiKey('');
                        }}>
                            {t('cancel')}
                        </Button>
                        <Button onClick={handleCreateApiKey}>
                            {t('apiKey.create')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* 编辑API Key对话框 */}
            <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
                <DialogContent className="sm:max-w-[500px]">
                    <DialogHeader>
                        <DialogTitle>{t('apiKey.editTitle')}</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4 py-4">
                        <div className="space-y-2">
                            <Label htmlFor="editKeyName">{t('apiKey.keyName')} *</Label>
                            <Input
                                id="editKeyName"
                                value={formData.keyName}
                                onChange={(e) => setFormData({ ...formData, keyName: e.target.value })}
                                placeholder={t('apiKey.keyNamePlaceholder')}
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>{t('apiKey.expiresAt')}</Label>
                            <DateTimePicker
                                date={editExpiresDate}
                                time={editExpiresTime}
                                onDateChange={setEditExpiresDate}
                                onTimeChange={setEditExpiresTime}
                                placeholder="选择过期时间（可选）"
                            />
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="editRemark">{t('apiKey.remark')}</Label>
                            <Input
                                id="editRemark"
                                value={formData.remark}
                                onChange={(e) => setFormData({ ...formData, remark: e.target.value })}
                                placeholder={t('apiKey.remarkPlaceholder')}
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => {
                            setShowEditDialog(false);
                            setEditingKey(null);
                            setFormData({ keyName: '', expiresAt: '', remark: '' });
                            setEditExpiresDate(undefined);
                            setEditExpiresTime('');
                        }}>
                            {t('cancel')}
                        </Button>
                        <Button onClick={handleUpdateApiKey}>
                            {t('save')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
};

export default ApiKeyPage; 