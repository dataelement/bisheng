export const MAX_MONTHLY_CREDITS = "9223372036854.775807";

/** Compare exact accounting units without rounding a decimal through Number. */
export function isValidMonthlyCredits(value: string): boolean {
  if (!/^(0|[1-9][0-9]{0,12})(\.[0-9]{1,6})?$/.test(value)) return false;
  const [whole, fraction = ""] = value.split(".");
  const tokens = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
  return tokens <= 9_223_372_036_854_775_807n;
}
