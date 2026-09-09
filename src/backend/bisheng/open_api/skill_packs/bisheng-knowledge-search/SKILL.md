---
name: bisheng-knowledge-search
description: Search knowledge bases through the BiSheng Open API.
---

# BiSheng knowledge search

Base URL: `{{BASE_URL}}`

Run `scripts/search.py` with a query and one or more knowledge-base IDs. The
script reads the personal access token from `BISHENG_API_KEY` and calls only
`POST {{BASE_URL}}/api/v2/filelib/retrieve`.

Example:

```bash
python scripts/search.py --base-url {{BASE_URL}} --query "release policy" --knowledge-base-id 12
```

Do not pass a user ID in the request body or add an identity-delegation header.
Personal access tokens always act as their holder.
