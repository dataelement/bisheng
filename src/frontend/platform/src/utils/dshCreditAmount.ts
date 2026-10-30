export const MAX_MONTHLY_CREDITS = "1000000";

/** Compare exact accounting units without rounding a decimal through Number. */
export function isValidMonthlyCredits(value: string): boolean {
  if (!/^(0|[1-9][0-9]{0,6})(\.[0-9])?$/.test(value)) return false;
  const [whole, fraction = ""] = value.split(".");
  const tokens = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
  return tokens <= BigInt(MAX_MONTHLY_CREDITS) * 1_000_000n;
}
