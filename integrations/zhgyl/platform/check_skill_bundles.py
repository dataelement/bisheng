"""Check generated Skill archives with actual 3.0.2 pure parser functions.

Uses AST extraction to avoid starting DB/cache/application imports. This proves
archive/frontmatter/content identity compatibility, not HTTP import permissions
or successful publication to MinIO; the platform must still perform those.
"""

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile
import zlib

import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True)
    args = parser.parse_args()
    source = (
        Path(__file__).resolve().parents[3]
        / "src/backend/bisheng/linsight/domain/services/skill_store.py"
    )
    names = {
        "parse_skill_md",
        "validate_skill_name",
        "_decode_zip_name",
        "unpack_zip_bytes",
        "_safe_rel_path",
        "bundle_content_hash",
    }
    constants = {"SKILL_MD", "MAX_NAME_LEN", "_NAME_RE", "_FRONTMATTER_RE"}
    tree = ast.parse(source.read_text())
    nodes = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
        and n.name in names
        or isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id in constants for t in n.targets)
    ]
    scope = {
        "hashlib": hashlib,
        "io": io,
        "re": re,
        "zipfile": zipfile,
        "zlib": zlib,
        "yaml": yaml,
        "PurePosixPath": PurePosixPath,
        "MAX_UNPACKED_CEILING": 1024 * 1024 * 1024,
        "BundleTooLargeError": ValueError,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
            str(source),
            "exec",
        ),
        scope,
    )
    rows = []
    for package in sorted((Path(args.runtime) / "skill-bundles").glob("*.zip")):
        files = scope["unpack_zip_bytes"](package.read_bytes())
        for path in files:
            scope["_safe_rel_path"](path)
        meta, body = scope["parse_skill_md"](files["SKILL.md"].decode())
        assert (
            meta["name"] == package.stem
            and scope["validate_skill_name"](meta["name"]) is None
        )
        assert isinstance(meta.get("description"), str) and body.strip()
        assert not any(
            path.endswith(("client.json", "credentials.json", ".env")) for path in files
        )
        rows.append(
            {
                "skill": meta["name"],
                "files": len(files),
                "skill_md_sha256": hashlib.sha256(files["SKILL.md"]).hexdigest(),
                "bundle_content_hash": scope["bundle_content_hash"](files),
            }
        )
    assert len(rows) == 5
    print(
        json.dumps(
            {
                "pure_302_parser_compatible": True,
                "http_import_tested": False,
                "skills": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
