import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Dialog } from "@/components/bs-ui/dialog";
import { getLinsightModelConfig } from "@/controllers/API/finetune";
import { describe, expect, it, vi } from "vitest";
import { ImageViewForm } from "./ImageView";

vi.mock("@/controllers/API/finetune", () => ({ getLinsightModelConfig: vi.fn() }));

describe("ImageViewForm", () => {
    it("keeps the saved visual model selected after options load", async () => {
        let resolveConfig: (value: unknown) => void = () => {};
        vi.mocked(getLinsightModelConfig).mockReturnValue(new Promise(resolve => { resolveConfig = resolve; }));
        const onSubmit = vi.fn();
        render(<Dialog open><ImageViewForm formData={{ model_id: "904" }} onSubmit={onSubmit} /></Dialog>);
        await act(async () => { resolveConfig({ models: [
            { id: "904", displayName: "Vision", visual: true },
            { id: "840", displayName: "Other Vision", visual: true },
        ] }); });
        await waitFor(() => expect(screen.getByRole("combobox")).toHaveTextContent("Vision"));
        fireEvent.click(screen.getByRole("button", { name: "save" }));
        expect(onSubmit).toHaveBeenCalledWith({ model_id: "904" });
        fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
        fireEvent.click(await screen.findByRole("option", { name: "Other Vision" }));
        expect(screen.getByRole("combobox")).toHaveTextContent("Other Vision");
        fireEvent.click(screen.getByRole("button", { name: "save" }));
        expect(onSubmit).toHaveBeenLastCalledWith({ model_id: "840" });
    });

    it("does not submit a saved model that is no longer available", async () => {
        vi.mocked(getLinsightModelConfig).mockResolvedValue({ models: [
            { id: "840", displayName: "Other Vision", visual: true },
        ] });
        const onSubmit = vi.fn();
        render(<Dialog open><ImageViewForm formData={{ model_id: "904" }} onSubmit={onSubmit} /></Dialog>);
        await act(async () => {});
        expect(screen.getByRole("combobox")).toHaveTextContent("pleaseSelect");
        expect(screen.getByRole("button", { name: "save" })).toBeDisabled();
        fireEvent.click(screen.getByRole("button", { name: "save" }));
        expect(onSubmit).not.toHaveBeenCalled();
    });
});
