"""Worker-only bounded HTTP client; public model input cannot choose its config."""
import argparse
from pathlib import Path
from contract import encode, loads, require
from fetch_history import fetch, fetch_inquiry, PRIVATE_ORIGIN
from tool_adapter import validate


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request-file',required=True)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--config',required=True)
    args=parser.parse_args()
    request=validate(loads(Path(args.request_file).read_bytes()))
    config=loads(Path(args.config).read_bytes())
    require(set(config)=={'base_url','token'} and config['base_url']==PRIVATE_ORIGIN)
    if request['action']=='history':
        result=fetch(config['base_url'],config['token'],request['query'],args.workspace,allow_private=True)
    else:
        require(request['action']=='inquiry')
        result=fetch_inquiry(config['base_url'],config['token'],request['target'],args.workspace,allow_private=True)
    print(encode(result).decode())


if __name__=='__main__':
    try:
        main()
    except Exception:
        print(encode({'status':'fetch_failed','terminal':True}).decode())
        raise SystemExit(1)
