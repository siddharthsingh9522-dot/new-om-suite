# OM Suite — Main App

Unified login (with admin approval) in front of four tools: TBB Party
Mail, Bill Generated Mail, Branch Detail Finder, Customer Search, and
OM Automation (CN/GST/Party).

See the **top-level `README.md`** (one folder up) for the full
picture — how login/admin-approval works, deployment notes, and the
GST-captcha/Chrome caveat.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
python app.py
```

First person to sign up at `/signup` becomes admin automatically.
Everyone else needs that admin to approve them at `/admin/users`
before they can log in.
