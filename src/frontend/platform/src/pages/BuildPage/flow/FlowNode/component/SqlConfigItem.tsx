import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next"; // 引入国际化

export default function SqlConfigItem({ data, onChange, onValidate }) {
    const { t } = useTranslation('flow'); // 使用国际化
    const [values, setValues] = useState(data.value);
    const [errors, setErrors] = useState({});

    const { db_address, db_name, db_username, db_password, open } = values;

    // 校验方法
    const handleValidate = () => {
        if (!open) return; // 开关关闭时无需校验

        const newErrors = {};
        const errorMessages = [];

        const validations = [
            {
                key: "db_address",
                value: db_address,
                max: 200,
                requiredMsg: t("dbAddressRequired"), // 数据库地址不可为空
                maxMsg: t("dbAddressTooLong"), // 数据库地址最多 200 字
            },
            {
                key: "db_name",
                value: db_name,
                max: 100,
                requiredMsg: t("dbNameRequired"), // 数据库名称不可为空
                maxMsg: t("dbNameTooLong"), // 数据库名称最多 100 字
            },
            {
                key: "db_username",
                value: db_username,
                max: 100,
                requiredMsg: t("dbUsernameRequired"), // 数据库用户名不可为空
                maxMsg: t("dbUsernameTooLong"), // 数据库用户名最多 100 字
            },
            {
                key: "db_password",
                value: db_password,
                requiredMsg: t("dbPasswordRequired"), // 数据库密码不可为空
            },
        ];

        validations.forEach(({ key, value, max, requiredMsg, maxMsg }) => {
            if (!value) {
                newErrors[key] = true;
                errorMessages.push(requiredMsg);
            } else if (max && value.length > max) {
                newErrors[key] = true;
                errorMessages.push(maxMsg);
            }
        });

        setErrors(newErrors);
        return errorMessages.length > 0 ? errorMessages[0] : false;
    };

    // 提供校验回调
    useEffect(() => {
        onValidate(handleValidate);
        return () => onValidate(() => { });
    }, [values, data.required]);

    const handleChange = (key, value) => {
        const newValues = { ...values, [key]: value };
        setValues(newValues);
        setErrors((prev) => ({ ...prev, [key]: false })); // 清除错误状态
        onChange(newValues);
    };

    return (
        <div className="node-item mb-4 relative" data-key={data.key}>
            {/* 开关 */}
            <Switch
                className="absolute -top-8 right-2"
                checked={open}
                onCheckedChange={(checked) => handleChange("open", checked)}
            />

            {/* 配置表单 */}
            {open && (
                <>
                    {/* 数据库地址 */}
                    <Label className="flex items-center bisheng-label">{t("dbAddress")}</Label> {/* 数据库地址 */}
                    <Input
                        className={`mt-2 nodrag ${errors.db_address ? "border-red-500" : ""}`}
                        value={db_address}
                        type="text"
                        onChange={(e) => handleChange("db_address", e.target.value)}
                    />

                    {/* 数据库名称 */}
                    <Label className="flex items-center bisheng-label mt-4">{t("dbName")}</Label> {/* 数据库名称 */}
                    <Input
                        className={`mt-2 nodrag ${errors.db_name ? "border-red-500" : ""}`}
                        value={db_name}
                        type="text"
                        onChange={(e) => handleChange("db_name", e.target.value)}
                    />

                    {/* 数据库用户名 */}
                    <Label className="flex items-center bisheng-label mt-4">{t("dbUsername")}</Label> {/* 数据库用户名 */}
                    <Input
                        className={`mt-2 nodrag ${errors.db_username ? "border-red-500" : ""}`}
                        value={db_username}
                        type="text"
                        onChange={(e) => handleChange("db_username", e.target.value)}
                    />

                    {/* 数据库密码 */}
                    <Label className="flex items-center bisheng-label mt-4">{t("dbPassword")}</Label> {/* 数据库密码 */}
                    <Input
                        className={`mt-2 nodrag ${errors.db_password ? "border-red-500" : ""}`}
                        value={db_password}
                        type="password"
                        onChange={(e) => handleChange("db_password", e.target.value)}
                    />
                </>
            )}
        </div>
    );
}
