#!/bin/bash

python3 api.py > log.txt 2>&1 &
python3 run_web.py