/**
 * @jest-environment node
 */
/* eslint-disable no-restricted-syntax -- fixtures use real Chinese KB names and queries */
import type { AgentEvent, AgentToolCall } from "~/api/chatApi";
import {
    describeKnowledgeCall,
    isKnowledgeToolCall,
    isReadableKnowledgeQuery,
    planKnowledgeRows,
    summariseKnowledgeBaseNames,
    compactKnowledgeQuery,
} from "./knowledgeRow";

/** Mirrors the backend chunk string (KnowledgeUtils.format_retrieved_chunk). */
function chunk(kbId: string, kbName: string, title: string, chunkId: string): string {
    return (
        `{<chunk_id>${chunkId}</chunk_id>\n<knowledge_base_id>${kbId}</knowledge_base_id>\n` +
        `<knowledge_base_name>${kbName}</knowledge_base_name>\n<file_title>${title}</file_title>\n` +
        `<file_abstract></file_abstract>\n<paragraph_content>x</paragraph_content>}`
    );
}

function failedKb(kbId: string, kbName: string, message: string): string {
    return (
        `<knowledge_base_id>${kbId}</knowledge_base_id><knowledge_base_name>${kbName}</knowledge_base_name>` +
        `<retrieval_error>${message}</retrieval_error>`
    );
}

function call(
    id: string,
    query: string,
    kbIds: string[] | undefined,
    results: string[],
    extra: Partial<AgentToolCall> = {},
): AgentToolCall {
    return {
        tool_call_id: id,
        tool_name: "search_knowledge_bases",
        tool_type: "knowledge",
        args: kbIds ? { query, knowledge_base_ids: kbIds } : { query },
        results,
        ...extra,
    };
}

const asEvent = (tc: AgentToolCall): AgentEvent => ({ type: "tool_call", ...tc }) as AgentEvent;
const think = (content: string): AgentEvent => ({ type: "thinking", content });

describe("describeKnowledgeCall", () => {
    it("reports KB, query, chunk count and distinct docs for a single-KB call", () => {
        const info = describeKnowledgeCall(
            call("c1", "项目全貌", ["1"], [
                chunk("1", "商情项目汇总", "A.docx", "rag_a:0"),
                chunk("1", "商情项目汇总", "A.docx", "rag_a:1"),
                chunk("1", "商情项目汇总", "B.pdf", "rag_b:0"),
            ]),
            {},
        );
        expect(info.kbKeys).toEqual(["1"]);
        expect(info.kbNames).toEqual(["商情项目汇总"]);
        expect(info.query).toBe("项目全貌");
        expect(info.queryReadable).toBe(true);
        expect(info.chunkCount).toBe(3);
        expect(info.docs).toEqual(["A.docx", "B.pdf"]);
        expect(info.hasError).toBe(false);
    });

    it("lists every searched KB and sums chunks across them", () => {
        const info = describeKnowledgeCall(
            call("c1", "q", ["1", "2"], [
                chunk("1", "KB1", "A.docx", "rag_a:0"),
                chunk("2", "KB2", "B.docx", "rag_b:0"),
                chunk("2", "KB2", "B.docx", "rag_b:1"),
            ]),
            {},
        );
        expect(info.kbKeys).toEqual(["1", "2"]);
        expect(info.kbNames).toEqual(["KB1", "KB2"]);
        expect(info.chunkCount).toBe(3);
    });

    it("falls back to the KBs found in the results when the call has no knowledge_base_ids", () => {
        const info = describeKnowledgeCall(call("c1", "q", undefined, [chunk("1", "KB1", "A.docx", "rag_a:0")]), {});
        expect(info.kbKeys).toEqual(["1"]);
        expect(info.kbNames).toEqual(["KB1"]);
    });

    it("uses the name map for an inflight call that has no results yet", () => {
        const inflight = call("c1", "q", ["1"], [], { inflight: true });
        expect(describeKnowledgeCall(inflight, { "1": "商情项目汇总" }).kbNames).toEqual(["商情项目汇总"]);
        expect(describeKnowledgeCall(inflight, {}).kbNames).toEqual([]);
    });

    it("marks a query that looks like search syntax as unreadable", () => {
        const info = describeKnowledgeCall(call("c1", "商情 AND 价值^2", ["1"], []), {});
        expect(info.queryReadable).toBe(false);
        expect(info.query).toBe("商情 AND 价值^2");
    });

    it("counts a retrieval error as an error and not as a chunk", () => {
        const info = describeKnowledgeCall(call("c1", "q", ["1"], [failedKb("1", "KB", "boom")]), {});
        expect(info.hasError).toBe(true);
        expect(info.chunkCount).toBe(0);
        expect(info.docs).toEqual([]);
    });

    it("reports zero chunks for an empty result", () => {
        const info = describeKnowledgeCall(call("c1", "q", ["1"], []), { "1": "KB" });
        expect(info.chunkCount).toBe(0);
        expect(info.docs).toEqual([]);
        expect(info.hasError).toBe(false);
    });

    it("parses results delivered as a JSON string", () => {
        const info = describeKnowledgeCall(
            call("c1", "q", ["1"], [], { results: JSON.stringify([chunk("1", "KB", "A.docx", "rag_a:0")]) }),
            {},
        );
        expect(info.chunkCount).toBe(1);
        expect(info.docs).toEqual(["A.docx"]);
    });
});

describe("summariseKnowledgeBaseNames", () => {
    it.each([
        [["A"], { shown: ["A"], total: 1 }],
        [["A", "B"], { shown: ["A", "B"], total: 2 }],
        [["A", "B", "C"], { shown: ["A"], total: 3 }],
        [[], { shown: [], total: 0 }],
    ])("summarises %j", (names, expected) => {
        expect(summariseKnowledgeBaseNames(names as string[])).toEqual(expected);
    });
});

describe("planKnowledgeRows", () => {
    const search = (id: string, kbIds: string[], doc = "A.docx", kbName = "KB") =>
        asEvent(call(id, `q-${id}`, kbIds, [chunk(kbIds[0], kbName, doc, `rag_${id}:0`)]));
    const web = { type: "tool_call", tool_call_id: "w", tool_name: "web_search", tool_type: "web", results: [] } as AgentEvent;

    it("numbers knowledge searches in event order, thinking segments produce no row", () => {
        const { rows } = planKnowledgeRows([search("c1", ["1"]), think("再想想"), search("c2", ["1"])]);
        expect(rows.get(0)).toEqual({ ordinal: 1 });
        expect(rows.has(1)).toBe(false);
        expect(rows.get(2)).toEqual({ ordinal: 2 });
    });

    it("numbers only knowledge searches", () => {
        const { rows } = planKnowledgeRows([web, search("c1", ["1"]), web, search("c2", ["2"], "B.docx", "KB2")]);
        expect(rows.get(1)).toEqual({ ordinal: 1 });
        expect(rows.get(3)).toEqual({ ordinal: 2 });
        expect(rows.has(0)).toBe(false);
    });

    it("leaves a failed call out of the rows", () => {
        const failed = asEvent(call("c2", "q", ["2"], [], { error: "timeout" }));
        const { rows } = planKnowledgeRows([search("c1", ["1"]), failed, search("c3", ["1"])]);
        expect(rows.has(1)).toBe(false);
        expect(rows.get(2)).toEqual({ ordinal: 2 });
    });

    it("collects KB names from every result so an inflight row can show its KB", () => {
        const inflight = asEvent(call("c2", "q2", ["1"], [], { inflight: true }));
        const { rows, kbNameById } = planKnowledgeRows([search("c1", ["1"], "A.docx", "商情项目汇总"), inflight]);
        expect(kbNameById).toEqual({ "1": "商情项目汇总" });
        expect(rows.get(1)).toEqual({ ordinal: 2 });
    });
});

describe("compactKnowledgeQuery", () => {
    it.each([
        ["项目全貌 价值总结", "项目全貌 价值总结"],
        ["价值总结 项目 价值总结", "价值总结 项目"],
        ["  项目   全貌  ", "项目 全貌"],
        ["项目全貌\u3000价值总结", "项目全貌 价值总结"],
        ["Agent agent AGENT 落地", "Agent 落地"],
        ["", ""],
    ])("compacts %j to %j", (input, expected) => {
        expect(compactKnowledgeQuery(input)).toBe(expected);
    });

    it("is what a row displays for the query", () => {
        const info = describeKnowledgeCall(call("c1", "价值 价值 总结", ["1"], []), {});
        expect(info.displayQuery).toBe("价值 总结");
        expect(info.query).toBe("价值 价值 总结");
    });
});

describe("isKnowledgeToolCall", () => {
    it("recognises knowledge calls by tool_type and by name heuristics", () => {
        expect(isKnowledgeToolCall({ tool_call_id: "1", tool_name: "x", tool_type: "knowledge" })).toBe(true);
        expect(isKnowledgeToolCall({ tool_call_id: "1", tool_name: "search_knowledge_bases" })).toBe(true);
        expect(isKnowledgeToolCall({ tool_call_id: "1", tool_name: "calc" })).toBe(false);
        expect(isKnowledgeToolCall({ tool_call_id: "1", tool_name: "web_search", tool_type: "web" })).toBe(false);
    });
});

describe("isReadableKnowledgeQuery", () => {
    it.each([["项目全貌 价值总结"], ["商情（2024）复盘"], ["market outlook or pricing"], ["NOTE on pricing"], ["a".repeat(40)]])(
        "accepts %s",
        (q) => expect(isReadableKnowledgeQuery(q)).toBe(true),
    );
    it.each([
        [""],
        ["   "],
        ["商情 AND 价值"],
        ["商情 OR 商业情报"],
        ["商情 NOT 草稿"],
        ["价值总结^2"],
        ["商情*"],
        ["商情~2"],
        ["(商情 价值) 总结"],
        ["[商情] 总结"],
        ["{商情} 总结"],
        ["title:商情"],
        ["file_name:总结.docx"],
        ["a".repeat(41)],
    ])("rejects %j", (q) => expect(isReadableKnowledgeQuery(q)).toBe(false));
});
