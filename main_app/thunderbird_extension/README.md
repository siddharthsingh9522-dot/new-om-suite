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

