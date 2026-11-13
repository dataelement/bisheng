#!/bin/sh
set -eu
# v2.5.10 paramtable merges configs/user.yaml after milvus.yaml.
[ -s /milvus/configs/user.yaml ] && [ -r /milvus/configs/user.yaml ] || exit 2
exec milvus run standalone
