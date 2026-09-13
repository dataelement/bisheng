---
name: bisheng-knowledge-search
description: Search the user's BiSheng knowledge bases and knowledge spaces (企业知识库检索). Use this whenever the user wants to 查知识库 / 检索资料 / 搜一下有没有… / 查内部文档、规范、流程、发版说明, or asks any question their organisation's knowledge base may answer. Read-only retrieval with the user's own permissions.
---

# BiSheng knowledge search

Base URL: `{{BASE_URL}}`

The personal access token comes from the environment variable `BISHENG_API_KEY`
and always acts as its holder. Full endpoint contract, response shapes,
pagination and the error-code table: `references/api.md` — read it before
composing requests.

## Workflow: list first, then retrieve

Knowledge-base IDs are numbers the user usually does not know. Never ask the
user for an ID before trying to find it yourself:

1. **List what the token can see** (both calls, they cover different types):

   ```bash
   python scripts/search.py --base-url {{BASE_URL}} --list-knowledge-bases space
   python scripts/search.py --base-url {{BASE_URL}} --list-knowledge-bases doc
   ```

   Pick the IDs whose names match the user's topic. If more results exist
   (`has_more` is true) pass `--cursor <next_cursor>` to continue. Department
   knowledge spaces are retrievable but do not appear in this listing — if the
   user names one, ask them for its ID (see `references/api.md`).

2. **Retrieve** against the chosen IDs:

   ```bash
   python scripts/search.py --base-url {{BASE_URL}} --query "release policy" --knowledge-base-id 12
   ```

   `--knowledge-base-id` may repeat; `--top-k` defaults to 10 (max 200).

3. **Cite what you used.** Each chunk carries `document_name`, `knowledge_id`,
   `document_id` and `chunk_index` — cite as
   `「document_name」(知识库 knowledge_id · 文档 document_id · 段 chunk_index)`
   so the user can find the original in BiSheng.

## When a call fails

The script prints the API's JSON error body to stderr; `status_code` there is
the business code. Look it up in `references/api.md` and follow its action —
in particular `26044` means the administrator restricted retrieval to the
user's own knowledge bases: tell the user to contact their administrator, do
not retry.

Do not pass a user ID in the request body or add an identity-delegation header.
Personal access tokens always act as their holder.
