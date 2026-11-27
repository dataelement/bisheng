import { generateKeyPairSync } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getLicenseStatus } from "./API/license";
import { getDepartmentLimitDetailApi, ldapLoginApi } from "./API/pro";
import { acceptManagementScope } from "./managementScope";
import request from "./request";
import { handleLdapEncrypt } from "@/pages/LoginPage/utils";

vi.mock("@bisheng/ui", () => ({ notification: { open: vi.fn() } }));

const originalAdapter = request.defaults.adapter;

beforeEach(() => {
    localStorage.clear();
});

afterEach(() => {
    request.defaults.adapter = originalAdapter;
    acceptManagementScope(null);
});

function mockGateway(responses: Record<string, unknown>) {
    const sent: Array<{ endpoint: string; tenant: unknown; data: unknown }> = [];
    request.defaults.adapter = async (config) => {
        const endpoint = `${config.method} ${config.url}`;
        sent.push({ endpoint, tenant: config.headers.get("X-Management-Tenant"), data: config.data });
        if (endpoint === "post /api/v1/admin/request-scope/bootstrap") {
            throw Object.assign(new Error("Unauthorized"), { config, response: { status: 401, data: {} } });
        }
        if (!Object.hasOwn(responses, endpoint)) {
            throw new Error(`Unexpected request: ${endpoint}`);
        }
        return { config, status: 200, statusText: "OK", headers: {}, data: responses[endpoint] };
    };
    return sent;
}

it("fetches the LDAP public key and sends an encrypted login request before any session exists", async () => {
    const { publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
    const sent = mockGateway({
        "get /api/getkey": publicKey.export({ type: "spki", format: "pem" }),
        "post /api/oauth2/ldap": { status_code: 200, data: { default_entry: "workspace" } },
    });
    const plaintext = "synthetic-password";

    const encrypted = await handleLdapEncrypt(plaintext);
    expect(encrypted).toEqual(expect.any(String));
    expect(encrypted).not.toBe(plaintext);
    await expect(ldapLoginApi("ldap-user", encrypted)).resolves.toEqual({ default_entry: "workspace" });

    expect(sent.map(({ endpoint }) => endpoint)).toEqual(["get /api/getkey", "post /api/oauth2/ldap"]);
    expect(sent.every(({ tenant }) => tenant === undefined)).toBe(true);
    expect(sent[1].data).toBe(JSON.stringify({ username: "ldap-user", password: encrypted }));
});

it("reads gateway license status without a management tenant", async () => {
    const license = { severity: "normal", expired: false };
    const sent = mockGateway({ "get /api/license/status": license });

    await expect(getLicenseStatus()).resolves.toEqual(license);
    expect(sent).toEqual([{ endpoint: "get /api/license/status", tenant: undefined, data: undefined }]);
});

it("blocks an ordinary business request if management scope cannot be established", async () => {
    const sent = mockGateway({});

    await expect(getDepartmentLimitDetailApi(1)).rejects.toMatchObject({ httpStatus: 401 });
    expect(sent.map(({ endpoint }) => endpoint)).toEqual(["post /api/v1/admin/request-scope/bootstrap"]);
});
