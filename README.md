# SmartVault Organizer Skill

A Claude Code skill that organizes SmartVault client vaults — renames files using standardized conventions and moves them into the correct subfolders.

> **Recommended:** Run this skill through the **[Claude Code CLI](https://code.claude.com/docs/en/quickstart)** (terminal). It provides persistent progress tracking, pause/resume, and revert across sessions. The web app and Claude for Work are supported but progress is lost when the session ends — see [Using the Web App or Claude for Work?](#using-the-web-app-or-claude-for-work) below.

## Installation

> Requires [Claude Code CLI](https://code.claude.com/docs/en/quickstart) installed. Run these commands in your terminal.

**Step 1 — Add the skill repository:**

```bash
claude plugin marketplace add https://github.com/eaby7210/smartvault-organizer-skil
```

**Step 2 — Install the skill:**

```bash
claude plugin install smartvault-organizer@smartvault-organizer-marketplace
```

**Step 3 — Reload plugins:**
```
/reload-plugins
```

**One-liner (Linux / Mac):**
```bash
claude plugin marketplace add https://github.com/eaby7210/smartvault-organizer-skil && claude plugin install smartvault-organizer@smartvault-organizer-marketplace
```

**One-liner (Windows PowerShell):**
```powershell
claude plugin marketplace add https://github.com/eaby7210/smartvault-organizer-skil; claude plugin install smartvault-organizer@smartvault-organizer-marketplace
```


**Step 4 — Configure credentials:**

After installing, tell Claude:
> "configure smartvault"

Claude will walk you through entering your SmartVault OAuth credentials. Nothing sensitive is stored in the repo.

---

## Offline Installation (ZIP)

No internet access or git required after downloading.

**Download the ZIP:**
- Go to [github.com/eaby7210/smartvault-organizer-skil](https://github.com/eaby7210/smartvault-organizer-skil)
- Click **Code → Download ZIP**
- Or direct link: [Download ZIP](https://github.com/eaby7210/smartvault-organizer-skil/archive/refs/heads/main.zip)

**Install on Linux / Mac:**
```bash
unzip smartvault-organizer-skil-main.zip
cd smartvault-organizer-skil-main
bash install.sh
```

**Install on Windows (PowerShell):**
```powershell
Expand-Archive smartvault-organizer-skil-main.zip
cd smartvault-organizer-skil-main
.\install.ps1
```

Then open Claude Code and run `/reload-plugins`.

---

## Requirements

- A SmartVault account with OAuth app credentials
- This skill installed in Claude

## Setup

After installing the skill, tell Claude:

> "configure smartvault"

Claude will:
1. Initialize the local database
2. Ask for your SmartVault OAuth credentials (`client_id`, `client_secret`, `email`)
3. Walk you through the OAuth login to obtain an access token

That's it — no manual file editing required.

## Usage

Once authenticated, just tell Claude:

> "organize smartvault"

Claude will:
1. Sync all clients from your SmartVault account
2. Process each client one at a time
3. Read and classify every document using AI
4. Move files into the correct subfolders with standardized names
5. Rename client root folders to the canonical format
6. Generate a summary report when done

## File Organization

Each client vault gets these subfolders:

| Subfolder | What goes in it |
|-----------|----------------|
| `EIN Letter` | IRS EIN confirmation letters |
| `Tax Documents` | W-2, 1099, 1040, K-1, etc. |
| `Receipts` | Insurance policies, expense receipts |
| `Entity Documents` | Business financials, loan statements |
| `Organizer` | Tax organizer worksheets |
| `Miscellaneous` | Everything else |

Client folders are renamed to `Last Name, First Name - email@example.com` (individuals) or `Business Name - email@example.com` (businesses).

## Skill Triggers

| Say this to Claude | What happens |
|--------------------|-------------|
| `"organize smartvault"` | Runs the full organization workflow |
| `"configure smartvault"` | Set or update credentials |
| `"set smartvault credentials"` | Same as above |
| `"run smartvault organizer"` | Same as organize |
| `"pause smartvault"` | Pause after the current client finishes |
| `"continue smartvault"` | Resume a paused run |
| `"revert [client name]"` | Undo all moves and renames for a client |

## Large Accounts

If you have a large number of clients or files, keep in mind:

- Claude processes **one client at a time** to avoid running out of memory or disk space. This is by design.
- A full run across hundreds of clients may take a long time. You can leave it running — Claude will work through the list and report when done.
- Claude may ask for your permission before moving or renaming files. For large runs, you can tell Claude **"yes to all"** upfront to avoid repeated prompts.
- You can pause at any time by telling Claude **"pause smartvault"**. Claude will finish the current client and stop. Say **"continue smartvault"** to pick up where it left off.
- Already-processed clients are tracked in the local database — resuming after a pause or crash will never reprocess completed work.
- If a session is interrupted mid-run for any reason (power failure, network drop, crash), just say `"organize smartvault"` or `"continue smartvault"` again. Every completed file and client is saved to the local database immediately — no work is repeated.
- Clients that fail (missing email, vault errors, etc.) are logged and skipped automatically — they won't block the rest of the run.

## Progress Database

All progress is tracked in a local SQLite database at `.mcp_state/app.db` in the skill folder.

> **If this folder is deleted or lost, all progress tracking is lost.** The skill will start fresh on the next run as if nothing was processed before. Files already organized in SmartVault will not be moved again (the skill skips files already inside the standard subfolders), but the run history and revert capability will be gone.

**Back up `.mcp_state/app.db`** if you want to preserve progress across machine migrations or reinstalls.

---

## Using the Web App or Claude for Work?

If you are using Claude via the **web app** (claude.ai) or **Claude for Work**, there is no persistent local storage between sessions. This means:

- **Progress does not carry over between sessions.** Each new session starts with a fresh database.
- **Already-organized files are still safe** — the skill automatically skips files already inside the standard subfolders (`EIN Letter`, `Tax Documents`, etc.), so previously organized files won't be moved again even without a database.
- **Revert will not work** across sessions — original file names and paths are only stored in the current session's database.
- **Reports** (`completed_clients.csv`) only reflect the current session's work.

For large accounts on the web app, plan to complete the full run in one session, or accept that each session will re-sync and re-process only the files not yet organized in SmartVault itself.

---

## Reports

After a run, Claude will summarize the results and two CSV files are saved locally:
- `completed_clients.csv` — successfully processed clients
- `failed_or_unready_clients.csv` — clients skipped with reasons
