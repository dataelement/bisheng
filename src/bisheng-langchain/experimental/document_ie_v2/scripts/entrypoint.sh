#!/bin/bash

pushd /opt/bisheng-ie
python3 document_extract.py > log.txt 2>&1 &
python3 run_web.py