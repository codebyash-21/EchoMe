#!/usr/bin/env bash
# EchoMe MVP – macOS / Linux launcher
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
python3 -m uvicorn backend.main:app --port 8000
