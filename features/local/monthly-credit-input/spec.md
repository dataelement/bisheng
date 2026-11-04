# Monthly credit input limits

Confirmed on 2026-10-29: administrators configure 0–1,000,000 credits per person per month, using integers or one decimal place. The default remains 500.

## Acceptance criteria

- Frontend validation and the credit-rule write API accept 0, 0.1, 999999.9, 1000000, and 1000000.0.
- Both boundaries reject values above 1000000 and values with more than one decimal place, including trailing zero digits.
- The Chinese, English, and Japanese hints describe the same range and precision; saving an invalid draft stays disabled.
- Stored historical allowances and legacy migration retain their exact values. Editing an allowance uses the current input rules; cancellation retains the saved value.
- Consumption, balance calculation, model multipliers, and the accounting storage range retain their existing precision.

## Design decision

The former form limit came from the signed 64-bit accounting maximum divided by 1,000,000. The administrator input contract now has a business limit. `CreditRuleInput` validates that contract, while `CreditRuleValue` carries exact historical amounts through migration and persistence. This separation preserves migration fidelity when the input precision changes.

## Verification

See `docs/STATUS.md` for the automated evidence and deployment acceptance status.
