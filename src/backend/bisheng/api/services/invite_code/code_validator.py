import random
import string


class VoucherGenerator:
    def __init__(self, length=10):
        self.length = length
        # Exclude similar letters and numbers: 'I', 'l', 'O', '0', '1'
        self.characters = ''.join(set(string.ascii_letters + string.digits) - set('IlOo01'))
        self.weights = [7, 9, 10, 5, 8, 4, 2, 1, 3]  # Weighting Factor
        self.check_digits = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2']  # Checksum Correspondence Form

    def generate_voucher(self):
        voucher_base = ''.join(random.choices(self.characters, k=self.length - 1))
        check_digit = self.calculate_check_digit(voucher_base)
        return voucher_base + check_digit

    def calculate_check_digit(self, voucher_base):
        total = sum(self.weights[i] * (ord(char) - ord('A') if char.isalpha() else int(char)) for i, char in
                    enumerate(voucher_base))
        remainder = total % 11
        return self.check_digits[remainder]

    def validate_voucher(self, voucher):
        if len(voucher) != 10:
            return False, "Invalid voucher length"

        voucher_base = voucher[:-1]
        provided_check_digit = voucher[-1]

        calculated_check_digit = self.calculate_check_digit(voucher_base)

        if provided_check_digit == calculated_check_digit:
            return True, "Valid voucher"
        else:
            return False, "Invalid voucher"


# Example Usage
if __name__ == "__main__":
    generator = VoucherGenerator()
    voucher_code = generator.generate_voucher()  # Generate a unique redemption code
    print(f"Generated voucher code: {voucher_code}")

    # Verify Redeem Code
    is_valid, info = generator.validate_voucher(voucher_code)
    print(f"Is valid: {is_valid}, Info: {info}")

    # Try to validate an invalid redemption code
    invalid_voucher_code = 'ABCDEFGHJK967'
    is_valid, info = generator.validate_voucher(invalid_voucher_code)
    print(f"Is valid: {is_valid}, Info: {info}")
