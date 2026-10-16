import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ModelItem } from "./ModelItem";
import { ModelItemConfig } from "./modelAdvancedParams";

const initial = {
  name: "GPT",
  model_name: "gpt-4o",
  model_type: "llm" as const,
  config: { user_kwargs: '{"temperature":0.1}', max_tokens: 20 },
};
const expand = () =>
  fireEvent.click(screen.getByRole("button", { name: "model.configureModel" }));
const advanced = () =>
  fireEvent.click(
    screen.getByRole("button", { name: "model.advancedParamsConfig" }),
  );
const editor = () => screen.getByRole("textbox");

describe("configured model parameters", () => {
  it("opens API-created object parameters and preserves them until an explicit edit", () => {
    const onConfig = vi.fn();
    render(<ModelItem type="openai" data={{ ...initial, config: { user_kwargs: { temperature: 0.3 } } }}
      onConfig={onConfig} onInput={vi.fn()} onDelete={vi.fn()} />);
    expand();
    advanced();
    expect(JSON.parse((editor() as HTMLTextAreaElement).value)).toEqual({ temperature: 0.3 });
    expect(onConfig).not.toHaveBeenCalled();
    fireEvent.change(editor(), { target: { value: '{"temperature":0.5}' } });
    fireEvent.click(screen.getByRole("button", { name: "model.save" }));
    expect(onConfig).toHaveBeenCalledWith({ user_kwargs: '{"temperature":0.5}' });
  });

  it("shows the old limit in the advanced editor and keeps opening read-only", () => {
    const onConfig = vi.fn();
    render(
      <ModelItem
        type="openai"
        data={initial}
        onConfig={onConfig}
        onInput={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expand();
    expect(screen.queryByRole("spinbutton")).toBeNull();
    advanced();
    expect(JSON.parse((editor() as HTMLTextAreaElement).value)).toEqual({
      temperature: 0.1,
      max_tokens: 20,
    });
    expect(onConfig).not.toHaveBeenCalled();
  });
  it("refreshes canonical values before opening and stores the edited limit once", () => {
    const onConfig = vi.fn();
    const view = render(
      <ModelItem
        type="openai"
        data={initial}
        onConfig={onConfig}
        onInput={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expand();
    view.rerender(
      <ModelItem
        type="openai"
        data={{
          ...initial,
          config: { max_tokens: 100, user_kwargs: '{"temperature":0.4}' },
        }}
        onConfig={onConfig}
        onInput={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    advanced();
    expect(JSON.parse((editor() as HTMLTextAreaElement).value).max_tokens).toBe(
      100,
    );
    fireEvent.change(editor(), {
      target: { value: '{"max_tokens":200,"temperature":0.4}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "model.save" }));
    expect(onConfig).toHaveBeenLastCalledWith({
      user_kwargs: '{"max_tokens":200,"temperature":0.4}',
    });
  });
  it("preserves unified parameters while toggling web search and reopening the editor", () => {
    const onConfig = vi.fn();
    function Harness() {
      const [config, setConfig] = useState<ModelItemConfig>(initial.config);
      return (
        <ModelItem
          type="qwen"
          data={{ ...initial, config }}
          onInput={vi.fn()}
          onDelete={vi.fn()}
          onConfig={(next) => {
            onConfig(next);
            setConfig(next);
          }}
        />
      );
    }
    render(<Harness />);
    expand();
    advanced();
    fireEvent.change(editor(), { target: { value: '{"max_tokens":256}' } });
    fireEvent.click(screen.getByRole("button", { name: "model.save" }));
    fireEvent.click(screen.getByRole("switch", { name: "model.webSearch" }));
    expect(onConfig).toHaveBeenLastCalledWith({
      user_kwargs: '{"max_tokens":256}',
      enable_web_search: true,
    });
    advanced();
    expect(JSON.parse((editor() as HTMLTextAreaElement).value)).toEqual({
      max_tokens: 256,
    });
  });
  it("keeps model input after collapsing a manually added row", () => {
    render(
      <ModelItem
        type="openai"
        data={{ name: "model 1", model_name: "", model_type: "llm" }}
        onConfig={vi.fn()}
        onInput={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "model.modelName" }), {
      target: { value: "custom-model" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "model.collapseConfiguration" }),
    );
    expand();
    expect(
      screen.getByRole("textbox", { name: "model.modelName" }),
    ).toHaveValue("custom-model");
    expect(screen.queryByRole("spinbutton")).toBeNull();
  });
  it("indicates incomplete TTS configuration while collapsed", () => {
    render(
      <ModelItem
        type="openai"
        data={{ name: "TTS", model_name: "tts-1", model_type: "tts" }}
        onConfig={vi.fn()}
        onInput={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText("model.configurationRequired")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expand();
    expect(screen.getByText("model.voiceType")).toBeInTheDocument();
  });
  it("validates JSON and leaves saved parameters intact when canceled", () => {
    const onConfig = vi.fn();
    render(
      <ModelItem
        type="openai"
        data={initial}
        onConfig={onConfig}
        onInput={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expand();
    advanced();
    fireEvent.change(editor(), { target: { value: "[]" } });
    fireEvent.click(screen.getByRole("button", { name: "model.save" }));
    expect(
      screen.getByText("model.errorInvalidJsonFormat"),
    ).toBeInTheDocument();
    expect(onConfig).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "model.cancel" }));
    advanced();
    expect(JSON.parse((editor() as HTMLTextAreaElement).value).max_tokens).toBe(
      20,
    );
  });
});
