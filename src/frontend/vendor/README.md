# Vendored frontend dependencies

`xlsx-0.20.3.tgz` is the unchanged official SheetJS 0.20.3 archive (2,409,319 bytes).

- Source: https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz
- SHA-512 integrity: `sha512-oLDq3jw7AcLqKWH2AhCpVTZl8mf6X2YReP+Neh0SJUzV/BdZYjth94tG5toiMB1PPrYtxOCfaoUCkvtuH+3AJA==`
- License: Apache-2.0, retained inside the official archive.

The workspace catalog pins the version. The root `pnpm.overrides.xlsx` resolves all consumers to this one local archive; pnpm 9.15.9 does not support `file:` entries directly in catalogs. Fresh empty-store offline installation was verified for the client, platform and nested shared-viewer directory layouts.

Docker builds include this file through the existing `COPY . /app`. Installation does not contact the SheetJS CDN. Other dependencies still use their configured registry.

For future upgrades, obtain the official archive, verify its provenance and integrity, then update the catalog, override, archive, lockfile and integrity regression test together. Run `pnpm test:config` and verify frozen offline installation from an empty store. Do not repack an installed node_modules directory as the vendor archive.

## Verification (2026-10-26)

- Official archive size and SHA-512 match the previous CDN lockfile entry.
- Complete workspace manifests accept `--frozen-lockfile --lockfile-only --offline --ignore-scripts` without rewriting the lockfile.
- An isolated workspace using the actual catalog version, root override and all three consumers' XLSX dependency declarations installs with `--frozen-lockfile --offline --ignore-scripts` and a fresh empty store; each consumer loads 0.20.3 and round-trips XLSX/XLS cells.
- `pnpm test:config`: 30 tests passed, including archive integrity and all three consumers' workbook/CSV compatibility cases.

Only the dependency source changes. Docker cache restructuring and unrelated feature branches are outside this change.
