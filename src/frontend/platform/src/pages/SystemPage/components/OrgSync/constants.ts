// A '****' sentinel on a secret field tells the backend to preserve the
// stored value (see sync_config.py `update_config`). Used across all
// provider field sets to keep the read/edit roundtrip safe.
export const MASKED_PLACEHOLDER = "****"
