import json
import re
from copy import deepcopy
from typing import Dict


class JsonFieldMasker:
    def __init__(self):
        # 定义敏感字段和对应的脱敏规则
        self.sensitive_fields = {
            'phone': self.mask_phone,
            'mobile': self.mask_phone,
            'phone_number': self.mask_phone,
            'tel': self.mask_phone,
            'id_card': self.mask_id_card,
            'identity_card': self.mask_id_card,
            'email': self.mask_email,
            'password': self.mask_password,
            'credit_card': self.mask_credit_card,
            'bank_card': self.mask_bank_card,
            'address': self.mask_address,
            'api_key': self.mask_api_key,
            'api_secret': self.mask_api_key,
            'openai_api_key': self.mask_api_key,
        }

        # 记录脱敏模式的正则表达式
        self.mask_patterns = {
            'phone': r'^\d{3}\*{4}\d{4}$',
            'id_card': r'^\d{6}\*{8}\d{4}$|^\d{3}\*{4}\d{3}\*{3}$',
            'email': r'^[^*@]+\*[^*@]*@',
            'password': r'^\*+$',
            'credit_card': r'^\d{4}\*{8,12}\d{4}$',
            'bank_card': r'^\d{4}\*{8,12}\d{4}$',
            'name': r'^[^*]+\*+[^*]*$',
            'address': r'^[^*]+\*+[^*]*$',
            'api_key': r'^\*+$',
            'api_secret': r'^\*+$',
            'openai_api_key': r'^\*+$',
        }

    def mask_api_key(self, api_key: str) -> str:
        """脱敏API密钥"""
        if not api_key:
            return api_key
        return '********'

    def mask_phone(self, phone: str) -> str:
        """脱敏手机号"""
        if not phone or len(phone) < 7:
            return phone
        return phone[:3] + '****' + phone[-4:]

    def mask_id_card(self, id_card: str) -> str:
        """脱敏身份证号"""
        if not id_card:
            return id_card
        if len(id_card) == 18:  # 18位身份证
            return id_card[:6] + '********' + id_card[-4:]
        elif len(id_card) == 15:  # 15位身份证
            return id_card[:3] + '****' + id_card[7:10] + '***'
        return '*' * 8

    def mask_email(self, email: str) -> str:
        """脱敏邮箱"""
        if '@' not in email:
            return email
        username, domain = email.split('@', 1)
        if len(username) > 2:
            masked_username = username[0] + '*' * 3 + username[-1]
        else:
            masked_username = '*' * len(username)
        return f'{masked_username}@{domain}'

    def mask_password(self, password: str) -> str:
        """脱敏密码"""
        return '********'

    def mask_credit_card(self, card: str) -> str:
        """脱敏信用卡号"""
        if not card or len(card) < 8:
            return card
        return card[:4] + '*' * (len(card) - 8) + card[-4:]

    def mask_bank_card(self, card: str) -> str:
        """脱敏银行卡号"""
        if not card or len(card) < 8:
            return card
        return card[:4] + '*' * (len(card) - 8) + card[-4:]

    def mask_name(self, name: str) -> str:
        """脱敏姓名"""
        if not name:
            return name
        if len(name) == 2:
            return name[0] + '*'
        elif len(name) > 2:
            return name[0] + '*' * (len(name) - 2) + name[-1]
        return '*'

    def mask_address(self, address: str) -> str:
        """脱敏地址"""
        if not address or len(address) <= 4:
            return address
        visible_length = min(4, len(address) // 3)
        return address[:visible_length] + '****' + address[-visible_length:]

    def is_masked_value(self, value: str, field_type: str) -> bool:
        """判断值是否已经是脱敏状态"""
        if not isinstance(value, str):
            return False

        if field_type in self.mask_patterns:
            pattern = self.mask_patterns[field_type]
            return bool(re.match(pattern, value))

        return False

    def mask_json(self, data: Dict) -> Dict:
        """
        脱敏JSON数据

        Args:
            data: 原始JSON数据

        Returns:
            脱敏后的数据
        """
        if not isinstance(data, dict):
            return data

        result = {}
        for key, value in data.items():
            if key in self.sensitive_fields:
                mask_func = self.sensitive_fields[key]
                if isinstance(value, str):
                    result[key] = mask_func(value)
                elif isinstance(value, dict):
                    # 如果值是字典，递归处理
                    result[key] = self.mask_json(value)
                else:
                    # 其他类型转换为字符串后脱敏
                    result[key] = mask_func(str(value))
            elif isinstance(value, dict):
                # 非敏感字段，递归处理嵌套字典
                result[key] = self.mask_json(value)
            else:
                # 非敏感字段，保持原样
                result[key] = value

        return result

    def update_json_with_masked(self, original: Dict, masked: Dict) -> Dict:
        """
        使用脱敏后的JSON更新原始JSON

        规则：如果脱敏后的字段值仍然是脱敏状态，则不更新；
             否则，用脱敏后的值更新原始值

        Args:
            original: 原始JSON数据
            masked: 脱敏后的JSON数据

        Returns:
            更新后的数据
        """
        if not isinstance(original, dict) or not isinstance(masked, dict):
            return masked if isinstance(masked, dict) else original

        result = deepcopy(original)

        for key, masked_value in masked.items():
            if key in result:
                original_value = result[key]

                if key in self.sensitive_fields:
                    # 敏感字段：检查是否已脱敏
                    if isinstance(masked_value, str) and isinstance(original_value, str):
                        if self.is_masked_value(masked_value, key):
                            # 仍然是脱敏状态，不更新
                            result[key] = original_value
                        else:
                            # 已恢复为未脱敏状态，更新
                            result[key] = masked_value
                    elif isinstance(masked_value, dict) and isinstance(original_value, dict):
                        # 嵌套字典，递归处理
                        result[key] = self.update_json_with_masked(original_value, masked_value)
                    else:
                        # 类型不匹配，保留原始值
                        result[key] = original_value
                else:
                    # 非敏感字段
                    if isinstance(masked_value, dict) and isinstance(original_value, dict):
                        # 嵌套字典，递归处理
                        result[key] = self.update_json_with_masked(original_value, masked_value)
                    else:
                        # 非嵌套字段，直接更新
                        result[key] = masked_value
            else:
                # 原始数据中没有的键，直接添加
                result[key] = masked_value

        return result

    def safe_update_json(self, original_json: str, masked_json: str) -> str:
        """
        安全的JSON更新：解析JSON字符串，更新，再序列化

        Args:
            original_json: 原始JSON字符串
            masked_json: 脱敏后的JSON字符串

        Returns:
            更新后的JSON字符串
        """
        try:
            original_data = json.loads(original_json)
            masked_data = json.loads(masked_json)

            if not isinstance(original_data, dict) or not isinstance(masked_data, dict):
                raise ValueError("JSON数据必须是对象类型")

            updated_data = self.update_json_with_masked(original_data, masked_data)
            return json.dumps(updated_data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as e:
            raise ValueError(f"无效的JSON数据: {e}")


# 示例使用
def main():
    masker = JsonFieldMasker()

    # 原始JSON数据
    original_data = {
        "user": {
            "id": 1,
            "name": "张三",
            "phone": "13800138000",
            "email": "zhangsan@example.com",
            "id_card": "110101199001011234",
            "bank_card": "6228480402564890018",
            "address": "北京市朝阳区建国门外大街1号",
            "details": {
                "emergency_contact": "李四",
                "emergency_phone": "13987654321"
            }
        },
        "password": "mysecret123",
        "timestamp": "2023-10-01T12:00:00Z"
    }

    print("原始JSON数据:")
    print(json.dumps(original_data, ensure_ascii=False, indent=2))
    print("\n" + "=" * 50 + "\n")

    # 1. 执行脱敏
    masked_data = masker.mask_json(original_data)
    print("脱敏后的JSON数据:")
    print(json.dumps(masked_data, ensure_ascii=False, indent=2))
    print("\n" + "=" * 50 + "\n")

    # 2. 模拟修改后的脱敏数据
    modified_masked_data = deepcopy(masked_data)
    # 修改一些字段
    modified_masked_data["user"]["name"] = "张*"  # 保持脱敏
    modified_masked_data["user"]["phone"] = "13812345678"  # 修改为新手机号
    modified_masked_data["user"]["email"] = "zhang@newmail.com"  # 修改邮箱
    modified_masked_data["password"] = "newpassword123"  # 修改密码
    modified_masked_data["timestamp"] = "2023-10-02T12:00:00Z"  # 修改时间戳

    print("修改后的脱敏JSON数据:")
    print(json.dumps(modified_masked_data, ensure_ascii=False, indent=2))
    print("\n" + "=" * 50 + "\n")

    # 3. 使用脱敏数据更新原始数据
    updated_data = masker.update_json_with_masked(original_data, modified_masked_data)

    print("更新后的JSON数据:")
    print(json.dumps(updated_data, ensure_ascii=False, indent=2))

    # 显示更新结果分析
    print("\n" + "=" * 50)
    print("字段更新情况分析:")
    print("-" * 30)

    def analyze_updates(orig, updated, path=""):
        for key in sorted(set(orig.keys()) | set(updated.keys())):
            current_path = f"{path}.{key}" if path else key

            if key in orig and key in updated:
                orig_val = orig[key]
                updated_val = updated[key]

                if orig_val != updated_val:
                    is_sensitive = key in masker.sensitive_fields
                    if is_sensitive:
                        is_masked = masker.is_masked_value(str(updated_val), key) if isinstance(updated_val,
                                                                                                str) else False
                        status = "✓ 已更新" if not is_masked else "✗ 未更新（仍为脱敏状态）"
                    else:
                        status = "✓ 已更新（非敏感字段）"

                    print(f"{current_path}: {status}")
                    print(f"  原始值: {orig_val}")
                    print(f"  新值: {updated_val}")
                elif isinstance(orig_val, dict) and isinstance(updated_val, dict):
                    analyze_updates(orig_val, updated_val, current_path)
            elif key in updated and key not in orig:
                print(f"{current_path}: ✓ 已添加（新字段）")
                print(f"  新值: {updated[key]}")

    analyze_updates(original_data, updated_data)

    # 测试字符串JSON处理
    print("\n" + "=" * 50)
    print("测试字符串JSON处理:")
    print("-" * 30)

    original_json_str = json.dumps(original_data, ensure_ascii=False)
    masked_json_str = json.dumps(modified_masked_data, ensure_ascii=False)

    try:
        updated_json_str = masker.safe_update_json(original_json_str, masked_json_str)
        print("更新后的JSON字符串:")
        print(updated_json_str)
    except ValueError as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()
