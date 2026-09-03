"""Knowledge-base ingestion constants."""

# Maximum characters allowed in a single chunk before it is rejected.
# Counted in Unicode code points (not bytes, not tokens) and kept well under the
# Milvus VARCHAR byte cap so that all-CJK chunks still fit after UTF-8 encoding.
KNOWLEDGE_MAX_CHUNK_CHARS: int = 10000
