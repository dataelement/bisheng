import { getAdvancedParamsTemplate } from "@/util/advancedParamsTemplates";
import { describe, expect, it } from "vitest";
import {
  advancedParamsPlaceholder,
  advancedParamsText,
  parseAdvancedParams,
  withAdvancedParams,
} from "./modelAdvancedParams";

describe("unified advanced model parameters", () => {
  it.each(["openai", "qwen", "qianfan", "ollama"])(
    "keeps the effective legacy limit for %s until the administrator edits it",
    (provider) => {
      const config = {
        max_tokens: 20,
        user_kwargs: '{"temperature":0.1,"max_tokens":100}',
      };
      const text = advancedParamsText(config, provider, "llm");
      expect(
        parseAdvancedParams(text)[
          provider === "ollama" ? "num_ctx" : "max_tokens"
        ],
      ).toBe(20);
      expect(parseAdvancedParams(text).temperature).toBe(0.1);
      const updated = withAdvancedParams(config, '{"max_tokens":200}', "llm");
      expect(updated.max_tokens).toBeUndefined();
      expect(parseAdvancedParams(updated.user_kwargs || "").max_tokens).toBe(
        200,
      );
      expect(config.max_tokens).toBe(20);
    },
  );
  it("keeps saved JSON intact and clears the old limit on an explicit reset", () => {
    const text = '{ "temperature": 0.4 }';
    expect(advancedParamsText({ user_kwargs: text }, "openai", "llm")).toBe(
      text,
    );
    expect(
      withAdvancedParams(
        { max_tokens: 20, enable_web_search: true, user_kwargs: text },
        "",
        "llm",
      ),
    ).toEqual({ enable_web_search: true, user_kwargs: "" });
  });
  it.each(["[]", "null", "42", '"text"', "{invalid"])(
    "preserves malformed saved text for correction and validates %s on save",
    (input) => {
      expect(
        advancedParamsText(
          { max_tokens: 20, user_kwargs: input },
          "openai",
          "llm",
        ),
      ).toBe(input);
      expect(() =>
        withAdvancedParams({ max_tokens: 20 }, input, "llm"),
      ).toThrow();
    },
  );
  it("offers provider-specific examples while keeping shared templates and embedding settings intact", () => {
    const before = JSON.stringify(getAdvancedParamsTemplate("openai", "llm"));
    expect(
      parseAdvancedParams(advancedParamsPlaceholder("openai", "llm"))
        .max_tokens,
    ).toBe(1024);
    expect(
      parseAdvancedParams(advancedParamsPlaceholder("ollama", "llm")).num_ctx,
    ).toBe(2048);
    expect(JSON.stringify(getAdvancedParamsTemplate("openai", "llm"))).toBe(
      before,
    );
    expect(
      parseAdvancedParams(advancedParamsPlaceholder("openai", "embedding")),
    ).not.toHaveProperty("max_tokens");
  });
});
