import { derivePersonalStorage } from "./personalStorage";

describe("derivePersonalStorage", () => {
    it("stays permissive until the server result arrives", () => {
        expect(derivePersonalStorage(undefined, undefined)).toMatchObject({
            status: "unknown",
            exhausted: false,
        });
        expect(derivePersonalStorage(0.5, undefined).status).toBe("unknown");
    });

    it("reports unlimited without a bar and picks the unit from usage", () => {
        expect(derivePersonalStorage(0.5, -1)).toMatchObject({
            status: "unlimited",
            usedText: "512 MB",
            totalText: "",
            exhausted: false,
        });
        expect(derivePersonalStorage(2.5, -1).usedText).toBe("2.5 GB");
    });

    it("switches both operands to MB when the cap is under 1 GB", () => {
        expect(derivePersonalStorage(0.1, 0.5)).toMatchObject({
            usedText: "102.4 MB",
            totalText: "512 MB",
        });
    });

    it("keeps both operands in GB once the cap reaches 1 GB", () => {
        expect(derivePersonalStorage(0.5, 2)).toMatchObject({
            usedText: "0.5 GB",
            totalText: "2 GB",
        });
    });

    it("crosses into the warning state at 80% of the cap", () => {
        expect(derivePersonalStorage(7.99, 10).status).toBe("normal");
        expect(derivePersonalStorage(8, 10).status).toBe("warning");
        expect(derivePersonalStorage(9.9, 10)).toMatchObject({
            status: "warning",
            exhausted: false,
            percent: 99,
        });
    });

    it("blocks writes at the cap and beyond, showing a full bar", () => {
        expect(derivePersonalStorage(10, 10)).toMatchObject({
            status: "full",
            exhausted: true,
            percent: 100,
        });
        expect(derivePersonalStorage(1.5, 0.5)).toMatchObject({
            status: "exceeded",
            exhausted: true,
            percent: 100,
            usedText: "1536 MB",
            totalText: "512 MB",
        });
    });

    it("treats a zero cap as full, or exceeded once anything is stored", () => {
        expect(derivePersonalStorage(0, 0)).toMatchObject({ status: "full", exhausted: true });
        expect(derivePersonalStorage(0.2, 0).status).toBe("exceeded");
    });

    it("derives status from raw values, not the rounded display text", () => {
        // Renders as "10 GB / 10 GB" but is still below the cap, so writes stay open.
        const almostFull = derivePersonalStorage(9.999, 10);
        expect(almostFull.usedText).toBe("10 GB");
        expect(almostFull.status).toBe("warning");
        expect(almostFull.exhausted).toBe(false);
    });

    it("exposes remaining bytes for size-aware upload checks", () => {
        expect(derivePersonalStorage(0.5, 2).remainingBytes).toBe(1.5 * 1024 ** 3);
        // Unknown or unlimited never blocks on batch size.
        expect(derivePersonalStorage(undefined, 2).remainingBytes).toBeNull();
        expect(derivePersonalStorage(0.5, -1).remainingBytes).toBeNull();
        // At or past the cap nothing is left, so any positive batch is over.
        expect(derivePersonalStorage(10, 10).remainingBytes).toBe(0);
        expect(derivePersonalStorage(1.5, 0.5).remainingBytes).toBeLessThan(0);
    });
});
