import MultiSelect from "@/components/bs-ui/select/multi";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Component, useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The real SearchInput renders an SVG asset that jsdom cannot mount.
vi.mock("@/components/bs-ui/input", async () => {
    const { forwardRef } = await import("react");
    return {
        SearchInput: forwardRef<HTMLInputElement, { placeholder?: string; onChange?: (e: unknown) => void }>(
            ({ placeholder, onChange }, ref) => <input ref={ref} placeholder={placeholder} onChange={onChange} />
        ),
    };
});

/**
 * jsdom has no IntersectionObserver. This stub keeps the one browser rule the
 * scroll-load cleanup depends on: `unobserve()` only accepts an Element and
 * throws a TypeError otherwise, e.g. Chrome's "Failed to execute 'unobserve'
 * on 'IntersectionObserver': parameter 1 is not of type 'Element'."
 */
class SpecIntersectionObserver {
    static instances: SpecIntersectionObserver[] = [];
    readonly targets = new Set<Element>();

    constructor(public readonly callback: IntersectionObserverCallback) {
        SpecIntersectionObserver.instances.push(this);
    }

    observe(target: Element) {
        if (!(target instanceof Element)) {
            throw new TypeError("Failed to execute 'observe' on 'IntersectionObserver': parameter 1 is not of type 'Element'.");
        }
        this.targets.add(target);
    }

    unobserve(target: Element) {
        if (!(target instanceof Element)) {
            throw new TypeError("Failed to execute 'unobserve' on 'IntersectionObserver': parameter 1 is not of type 'Element'.");
        }
        this.targets.delete(target);
    }

    disconnect() {
        this.targets.clear();
    }

    takeRecords() {
        return [];
    }

    intersect(isIntersecting: boolean) {
        const entries = [...this.targets].map((target) => ({ target, isIntersecting }) as IntersectionObserverEntry);
        this.callback(entries, this as unknown as IntersectionObserver);
    }
}

class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
    state = { error: null as Error | null };

    static getDerivedStateFromError(error: Error) {
        return { error };
    }

    render() {
        return this.state.error ? <div role="alert">{this.state.error.message}</div> : this.props.children;
    }
}

const options = [
    { label: "Knowledge A", value: "1" },
    { label: "Knowledge B", value: "2" },
];

let showSelect: (show: boolean) => void = () => {};

function Harness({ onScrollLoad }: { onScrollLoad: (name: string) => void }) {
    const [show, setShow] = useState(true);
    showSelect = setShow;
    return (
        <Boundary>
            {show && (
                <MultiSelect
                    id="knowledge"
                    multiple
                    value={[]}
                    options={options}
                    placeholder="pick knowledge"
                    onScrollLoad={onScrollLoad}
                    onChange={() => {}}
                />
            )}
        </Boundary>
    );
}

async function openSelect() {
    await userEvent.setup().click(screen.getByRole("combobox"));
    await screen.findByText("Knowledge A");
}

describe("MultiSelect scroll load", () => {
    const original = (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;

    beforeEach(() => {
        SpecIntersectionObserver.instances = [];
        (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = SpecIntersectionObserver;
        vi.spyOn(console, "error").mockImplementation(() => {});
    });

    afterEach(() => {
        (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = original;
        vi.restoreAllMocks();
    });

    it("does not crash when the select is unmounted while its dropdown is open", async () => {
        render(<Harness onScrollLoad={vi.fn()} />);
        await openSelect();

        const observer = SpecIntersectionObserver.instances.at(-1)!;
        expect(observer.targets.size).toBe(1);

        act(() => showSelect(false));

        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        expect(observer.targets.size).toBe(0);
    });

    it("stops observing the footer when the dropdown closes", async () => {
        render(<Harness onScrollLoad={vi.fn()} />);
        await openSelect();
        const observer = SpecIntersectionObserver.instances.at(-1)!;

        await userEvent.setup().keyboard("{Escape}");

        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        expect(observer.targets.size).toBe(0);

        act(() => showSelect(false));
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("still loads the next page when the list footer scrolls into view", async () => {
        const onScrollLoad = vi.fn();
        render(<Harness onScrollLoad={onScrollLoad} />);
        await openSelect();

        const observer = SpecIntersectionObserver.instances.at(-1)!;
        act(() => observer.intersect(false));
        expect(onScrollLoad).not.toHaveBeenCalled();

        act(() => observer.intersect(true));
        expect(onScrollLoad).toHaveBeenCalledWith("");

        await userEvent.setup().keyboard("{Escape}");
    });
});
