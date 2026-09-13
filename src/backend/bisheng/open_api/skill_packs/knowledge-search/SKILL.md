---
name: knowledge-search
description: Search the user's knowledge bases and knowledge spaces (企业知识库检索). Use this whenever the user wants to 查知识库 / 检索资料 / 搜一下有没有… / 查内部文档、规范、流程、发版说明, or asks any question their organisation's knowledge base may answer. Read-only retrieval with the user's own permissions.
---

# Knowledge search

Base URL: `{{BASE_URL}}` — already baked into `scripts/search.py`; pass
`--base-url` only if the user says the platform moved. Full endpoint contract,
response shapes, pagination and the error-code table: `references/api.md` —
read it before composing requests.

## Credentials: configure once, then forget

The script finds the user's personal access token by itself, in this order:

1. the environment variable `KNOWLEDGE_API_KEY` (per-process override);
2. this skill's own credentials file — `~/.config/knowledge-search/credentials.json`
   (`%APPDATA%\knowledge-search\credentials.json` on Windows), one profile per
   Base URL, written by `--configure` and readable only by the current user.

One-time setup, run when the user hands you their key (they generate it on the
platform's **AI 助手接入 / AI assistant access** settings page):

```bash
python3 scripts/search.py --configure --api-key <key>
```

(`python` instead of `python3` on Windows.) It checks the key against the
platform, stores it and prints only a masked form. From then on every call in
every new session just works. Rules:

- If a call exits with `No API key for …`, do exactly what the message says:
  ask the user for their key and run `--configure`. Do **not** search the file
  system, shell profiles or environment for it.
- Never write the key into shell profile files (`.zshenv`, `.bashrc`, …), agent
  memory, notes or any other file. `--configure` is the only place it lives.
- On `HTTP 401` the error names where the rejected key came from (environment
  variable or credentials file) and the fix — follow it instead of retrying.

## Workflow: list first, then retrieve

Knowledge-base IDs are numbers the user usually does not know. Never ask the
user for an ID before trying to find it yourself:

1. **List what the token can see** (both calls, they cover different types):

   ```bash
   python3 scripts/search.py --list-knowledge-bases space
   python3 scripts/search.py --list-knowledge-bases doc
   ```

   Pick the IDs whose names match the user's topic. If more results exist
   (`has_more` is true) pass `--cursor <next_cursor>` to continue. Department
   knowledge spaces are retrievable but do not appear in this listing — if the
   user names one, ask them for its ID (see `references/api.md`).

2. **Retrieve** against the chosen IDs:

   ```bash
   python3 scripts/search.py --query "release policy" --knowledge-base-id 12
   ```

   `--knowledge-base-id` may repeat; `--top-k` defaults to 10 (max 200).

3. **Cite what you used.** Each chunk carries `document_name`, `knowledge_id`,
   `document_id` and `chunk_index` — cite as
   `「document_name」(知识库 knowledge_id · 文档 document_id · 段 chunk_index)`
   so the user can find the original on the platform.

## When a call fails

The script prints the API's JSON error body to stderr; `status_code` there is
the business code. Look it up in `references/api.md` and follow its action —
in particular `26044` means the administrator restricted retrieval to the
user's own knowledge bases: tell the user to contact their administrator, do
not retry.

Do not pass a user ID in the request body or add an identity-delegation header.
Personal access tokens always act as their holder.
