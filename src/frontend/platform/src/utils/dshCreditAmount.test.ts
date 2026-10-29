import { expect, it } from "vitest";
import { isValidMonthlyCredits, MAX_MONTHLY_CREDITS } from "./dshCreditAmount";

it.each(["0", "0.000000", "0.000001", "500", "1.25", "9223372036854", "9223372036854.775806", MAX_MONTHLY_CREDITS])("accepts the exact credit amount %s", value => {
  expect(isValidMonthlyCredits(value)).toBe(true);
});

it.each(["", "-1", "01", "1e3", "NaN", "Infinity", " 500", "500 ", "1.", "0.0000001", "9223372036854.775808", "9223372036855", "9999999999999", "10000000000000"])("rejects the credit amount %s", value => {
  expect(isValidMonthlyCredits(value)).toBe(false);
});
