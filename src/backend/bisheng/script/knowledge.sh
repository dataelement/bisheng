#!/bin/bash

export PYTHONPATH="./"
run_mode=${1:-convert_all}
knowledge_id=${2:-0}

if [ "$run_mode" = "convert_all" ]; then
    echo "Converting all knowledge"
    python bisheng/script/knowledge_data_convert.py --mode convert_all
elif [ "$run_mode" = "convert_one" ]; then
    echo "Converting one knowledge : $knowledge_id"
    python bisheng/script/knowledge_data_convert.py --mode convert_one --id ${knowledge_id}
elif [ "$run_mode" = "scan_all" ]; then
    echo "Scanning all knowledge files..."
    python bisheng/script/knowledge_data_fix.py --mode scan_all
elif [ "$run_mode" = "scan_one" ]; then
    echo "Scanning single knowledge : $knowledge_id"
    python bisheng/script/knowledge_data_fix.py --mode scan_one --id ${knowledge_id}
elif [ "$run_mode" = "fix_all" ]; then
    echo "Fixing all knowledge files..."
    python bisheng/script/knowledge_data_fix.py --mode fix_all
elif [ "$run_mode" = "fix_one" ]; then
    echo "Fixing single knowledge : $knowledge_id"
    python bisheng/script/knowledge_data_fix.py --mode fix_one --id ${knowledge_id}
else
    echo "Invalid run mode. Use 'convert_all', 'convert_one', 'scan_all', 'scan_one', 'fix_all', or 'fix_one'."
    exit 1
fi
