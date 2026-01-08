import json
import re
from copy import deepcopy
from typing import Dict


class JsonFieldMasker:
    def __init__(self):
        # Define sensitive fields and corresponding desensitization rules
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
            'siliconflow_api_key': self.mask_api_key,
            'email_password': self.mask_api_key,
            'jina_api_key': self.mask_api_key,
            'app_secret': self.mask_api_key,
        }

        # Record regular expressions for desensitization mode
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
            'siliconflow_api_key': r'^\*+$',
            'email_password': r'^\*+$',
            'jina_api_key': r'^\*+$',
            'app_secret': r'^\*+$',
        }

    def mask_api_key(self, api_key: str) -> str:
        """ImmunosuppressionAPIKey"""
        if not api_key:
            return api_key
        return '********'

    def mask_phone(self, phone: str) -> str:
        """Desensitized phone number"""
        if not phone or len(phone) < 7:
            return phone
        return phone[:3] + '****' + phone[-4:]

    def mask_id_card(self, id_card: str) -> str:
        """Desensitization ID number"""
        if not id_card:
            return id_card
        if len(id_card) == 18:  # 18bits ID card
            return id_card[:6] + '********' + id_card[-4:]
        elif len(id_card) == 15:  # 15bits ID card
            return id_card[:3] + '****' + id_card[7:10] + '***'
        return '*' * 8

    def mask_email(self, email: str) -> str:
        """Desensitization email"""
        if '@' not in email:
            return email
        username, domain = email.split('@', 1)
        if len(username) > 2:
            masked_username = username[0] + '*' * 3 + username[-1]
        else:
            masked_username = '*' * len(username)
        return f'{masked_username}@{domain}'

    def mask_password(self, password: str) -> str:
        """Desensitization password"""
        return '********'

    def mask_credit_card(self, card: str) -> str:
        """Desensitized credit card number"""
        if not card or len(card) < 8:
            return card
        return card[:4] + '*' * (len(card) - 8) + card[-4:]

    def mask_bank_card(self, card: str) -> str:
        """Desensitized bank card number"""
        if not card or len(card) < 8:
            return card
        return card[:4] + '*' * (len(card) - 8) + card[-4:]

    def mask_name(self, name: str) -> str:
        """Desensitization Name"""
        if not name:
            return name
        if len(name) == 2:
            return name[0] + '*'
        elif len(name) > 2:
            return name[0] + '*' * (len(name) - 2) + name[-1]
        return '*'

    def mask_address(self, address: str) -> str:
        """Desensitization Address"""
        if not address or len(address) <= 4:
            return address
        visible_length = min(4, len(address) // 3)
        return address[:visible_length] + '****' + address[-visible_length:]

    def is_masked_value(self, value: str, field_type: str) -> bool:
        """Determine if the value is already desensitized"""
        if not isinstance(value, str):
            return False

        if field_type in self.mask_patterns:
            pattern = self.mask_patterns[field_type]
            return bool(re.match(pattern, value))

        return False

    def mask_json(self, data: Dict) -> Dict:
        """
        ImmunosuppressionJSONDATA

        Args:
            data: OriginalJSONDATA

        Returns:
            Data after desensitization
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
                    # If the value is a dictionary, recursive processing
                    result[key] = self.mask_json(value)
                else:
                    # Desensitization after conversion of other types to strings
                    result[key] = mask_func(str(value))
            elif isinstance(value, dict):
                # Insensitive fields, recursive processing of nested dictionaries
                result[key] = self.mask_json(value)
            else:
                # Non-sensitive fields, leave as is
                result[key] = value

        return result

    def update_json_with_masked(self, original: Dict, masked: Dict) -> Dict:
        """
        After desensitizationJSONUpdate originalJSON

        Rule: If the field value after desensitization is still desensitized, it will not be updated;
             Otherwise, update the original value with the desensitized value

        Args:
            original: OriginalJSONDATA
            masked: After desensitizationJSONDATA

        Returns:
            Updated data
        """
        if not isinstance(original, dict) or not isinstance(masked, dict):
            return masked if isinstance(masked, dict) else original

        result = deepcopy(original)

        for key, masked_value in masked.items():
            if key in result:
                original_value = result[key]

                if key in self.sensitive_fields:
                    # Sensitive Fields: Check for desensitization
                    if isinstance(masked_value, str) and isinstance(original_value, str):
                        if self.is_masked_value(masked_value, key):
                            # Still desensitized, don't update
                            result[key] = original_value
                        else:
                            # Restored to desensitized, updated
                            result[key] = masked_value
                    elif isinstance(masked_value, dict) and isinstance(original_value, dict):
                        # Nested dictionaries, recursive processing
                        result[key] = self.update_json_with_masked(original_value, masked_value)
                    else:
                        # Type mismatch, keep original value
                        result[key] = original_value
                else:
                    # Non-Sensitive Fields
                    if isinstance(masked_value, dict) and isinstance(original_value, dict):
                        # Nested dictionaries, recursive processing
                        result[key] = self.update_json_with_masked(original_value, masked_value)
                    else:
                        # Non-nested fields, update directly
                        result[key] = masked_value
            else:
                # Keys that are not in the original data, add them directly
                result[key] = masked_value

        return result

    def safe_update_json(self, original_json: str, masked_json: str) -> str:
        """
        SafeJSONUpdate: InsightsJSONString, update, re-serialize

        Args:
            original_json: OriginalJSONString
            masked_json: After desensitizationJSONString

        Returns:
            Post UpdateJSONString
        """
        try:
            original_data = json.loads(original_json)
            masked_data = json.loads(masked_json)

            if not isinstance(original_data, dict) or not isinstance(masked_data, dict):
                raise ValueError("JSONData must be of object type")

            updated_data = self.update_json_with_masked(original_data, masked_data)
            return json.dumps(updated_data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as e:
            raise ValueError(f"InvalidJSONDATA: {e}")


# Example Use
def main():
    masker = JsonFieldMasker()

    # OriginalJSONDATA
    original_data = {
        "user": {
            "id": 1,
            "name": "Zhang San",
            "phone": "13800138000",
            "email": "zhangsan@example.com",
            "id_card": "110101199001011234",
            "bank_card": "6228480402564890018",
            "address": "Jianguomenwai Street, Chaoyang District, Beijing1.",
            "details": {
                "emergency_contact": "Lisi",
                "emergency_phone": "13987654321"
            }
        },
        "password": "mysecret123",
        "timestamp": "2023-10-01T12:00:00Z"
    }

    print("OriginalJSONDATA:")
    print(json.dumps(original_data, ensure_ascii=False, indent=2))
    print("\n" + "=" * 50 + "\n")

    # 1. Perform desensitization
    masked_data = masker.mask_json(original_data)
    print("After desensitizationJSONDATA:")
    print(json.dumps(masked_data, ensure_ascii=False, indent=2))
    print("\n" + "=" * 50 + "\n")

    # 2. Simulated modified desensitization data
    modified_masked_data = deepcopy(masked_data)
    # Modify some fields
    modified_masked_data["user"]["name"] = "Pcs*"  # Keep desensitization
    modified_masked_data["user"]["phone"] = "13812345678"  # Change to a new phone number
    modified_masked_data["user"]["email"] = "zhang@newmail.com"  # Modify email
    modified_masked_data["password"] = "newpassword123"  # Change the password
    modified_masked_data["timestamp"] = "2023-10-02T12:00:00Z"  # Revision timestamp

    print("Modified desensitizationJSONDATA:")
    print(json.dumps(modified_masked_data, ensure_ascii=False, indent=2))
    print("\n" + "=" * 50 + "\n")

    # 3. Update raw data with desensitized data
    updated_data = masker.update_json_with_masked(original_data, modified_masked_data)

    print("Post UpdateJSONDATA:")
    print(json.dumps(updated_data, ensure_ascii=False, indent=2))

    # Show updated results analysis
    print("\n" + "=" * 50)
    print("Field Update Situation Analysis:")
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
                        status = "✓ Updated" if not is_masked else "✗ Not updated (still desensitized)"
                    else:
                        status = "✓ Updated (non-sensitive field)"

                    print(f"{current_path}: {status}")
                    print(f"  Original Value: {orig_val}")
                    print(f"  New Value: {updated_val}")
                elif isinstance(orig_val, dict) and isinstance(updated_val, dict):
                    analyze_updates(orig_val, updated_val, current_path)
            elif key in updated and key not in orig:
                print(f"{current_path}: ✓ Added (new field)")
                print(f"  New Value: {updated[key]}")

    analyze_updates(original_data, updated_data)

    # Test StringJSON<g id="Bold">Medical Treatment:</g>
    print("\n" + "=" * 50)
    print("Test StringJSON<g id='Bold'>Medical Treatment:</g>:")
    print("-" * 30)

    original_json_str = json.dumps(original_data, ensure_ascii=False)
    masked_json_str = json.dumps(modified_masked_data, ensure_ascii=False)

    try:
        updated_json_str = masker.safe_update_json(original_json_str, masked_json_str)
        print("Post UpdateJSONString:")
        print(updated_json_str)
    except ValueError as e:
        print(f"Error-free: {e}")


if __name__ == "__main__":
    main()
