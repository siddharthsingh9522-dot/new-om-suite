# Auto Bill Intelligence — Thunderbird Extension

## What it does
1. Reads Thunderbird Sent folders (or specific folders you choose — see "Search Folders" below).
2. Finds historical Auto Bill mails matching branch/party/bill/subject patterns.
3. Extracts TO/CC/BCC from the best historical Sent copy.
4. Sends the match profile back to the Flask app with a confidence score.
5. When auto-send is explicitly enabled, processes send jobs from the Flask queue using Thunderbird's configured identity/SMTP.
6. Adds the generated branch CSV as an attachment.

## Install
Thunderbird -> Add-ons and Themes -> gear -> Debug Add-ons -> Load Temporary Add-on -> select `manifest.json`.
For a permanent local install, package the folder as an XPI and sign it if your Thunderbird policy requires signing.

## Configure
Open extension Options:
- Web App URL: `http://127.0.0.1:5000`
- Bridge Token: aapke web app ke `/bridge` page se milega (per-user token, `.env` mein nahi hai)
- App Username: web app ka apna username
- Keep Auto-send OFF during initial testing.

## Search Folders (naya)
Options page mein "Search Folders" section se aap specific folder(s) choose kar sakte ho jahan
match dhoonda jaye — sirf auto-detected "Sent" folder tak limited nahi hai ab.

- "Folder List Refresh Karein" dabao — sabhi accounts ke saare folders (nested bhi) checkbox list mein dikhengi
- Jo bhi folder(s) chahiye unko tick karo (jaise ek "TBB Archive" ya "Bills 2026" jaisi custom folder)
- "Save Settings" dabao
- **Kuch bhi select nahi karoge to purana default behaviour chalega** — har account ka auto-detected Sent folder

The extension uses Thunderbird's WebExtension `messages` and `compose` APIs. Automatic background sending requires a Thunderbird build that supports the relevant send API; the compose send path is used for broad compatibility.


## v1.1.0 — Audit fixes & improvements
Audited against a working sibling extension (friend's GR Mail AI Assistant) and against this
extension's own Flask backend (`/api/bridge/*` in `app.py`). Changes:

1. **`strict_min_version` lowered from `115.15.0` → `102.0`.** This was the single most likely
   reason the extension silently "didn't work" while another extension on the same Thunderbird
   install did: if your Thunderbird build is below 115.15, Thunderbird disables/refuses to load
   this add-on entirely, with no popup error — it just looks dead. None of the WebExtension APIs
   this extension uses require 115+, so the floor is now 102 (same baseline the working sibling
   extension uses).
2. **Silent no-op fixed.** Previously, if Bridge Token / App Username weren't filled in Options,
   `processJobs()` returned instantly with zero indication anywhere — popup just showed settings,
   nothing else. Now every poll cycle records what happened (or why it didn't) to storage, and the
   popup shows a live status dot (green/red/grey) plus the last error in plain language.
3. **`notifications` permission was declared but never used.** Now you get a native desktop
   notification when a match is found, when a mail is sent, or when a job fails — so you don't have
   to keep the popup open or dig through the Browser Console.
4. **Dead `pollSeconds` setting removed.** The old code hardcoded a 5-second poll regardless of this
   setting, and Thunderbird/Firefox clamp background alarms to a 1-minute minimum anyway — so 5s was
   never actually happening. Replaced with a real, working "Check every N minutes" dropdown in
   Options (1/2/5/10/30 min), applied immediately via a `reschedule` message on Save.
5. **"Test Connection" is now smarter.** It distinguishes a network failure (backend not reachable)
   from a 401 (wrong Token/Username) and gives a specific next step for each, and updates the same
   status the popup shows.
6. Added extension icons (was missing, `browser_action.default_icon` previously unset).

## Setup checklist if it's still not polling
1. Confirm your Thunderbird version: Help → About Thunderbird. Must be 102 or newer.
2. Flask app running and reachable at the exact URL in Options → Web App URL (no trailing slash).
3. Options → Bridge Token: copied fresh from the web app's `/bridge` page, and App Username matches
   your login username exactly (case-insensitive, but no typos/spaces).
4. Options → Bridge enabled: ON. Auto-send stays OFF until you've verified matches look right.
5. Click "Test Connection" — read the error text if it's red, it now tells you exactly what's wrong.

## v1.1.1 — real send bug fixed
Found via the new "Job failed" desktop notification (the diagnostics added in v1.1.0 are what
surfaced this — previously this failure happened silently with no visible error at all):

**`compose.addAttachment` was called with the wrong shape.** The code built the attachment object
as `{ name, url: <data-url>, type }`. Current Thunderbird only accepts either `{ file: File }`
(a real File object) or `{ id: <number> }` (to reference/replace an existing attachment) — passing
`url`/`type` fails schema validation with exactly the error you saw: *"Value must either: not
contain the unexpected properties [type, url], or contain the required 'id' property."*
Every single auto-send with an attachment was failing at this line, unconditionally.

Fixed: the attachment bytes fetched from the backend are now wrapped in a real `File` object and
passed as `{ file }`, matching Thunderbird's current `compose.addAttachment` schema. Also removed
the now-unused `blobToDataUrl` helper.
