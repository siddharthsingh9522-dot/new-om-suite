#!/usr/bin/env bash
set -e
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
python3 -c 'import secrets; print("Generated FLASK_SECRET:", secrets.token_urlsafe(48)); print("Generated THUNDERBIRD_BRIDGE_TOKEN:", secrets.token_urlsafe(48))'
echo "Setup complete. Edit .env, then run: python3 app.py"
