#!/usr/bin/python3
"""Git HTTPS credential bridge for the dedicated publisher identity only."""
import os
from pathlib import Path
import sys

prompt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
if "username" in prompt:
    print("x-access-token")
elif "password" in prompt:
    token_file = Path(os.environ["ALFRED_PUBLISH_TOKEN_FILE"])
    token = token_file.read_text().strip()
    if not token or "\n" in token or "\r" in token:
        raise SystemExit(1)
    print(token)
else:
    raise SystemExit(1)
