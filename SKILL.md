---
name: smartvault-organizer
description: |
  Organizes SmartVault accounting client vaults: renames files using standardized
  naming conventions, moves documents into correct subfolders, and renames client
  root folders to the canonical "Name - Email" format. Processes one client at a
  time to prevent disk exhaustion.
version: 1.0.0
tools:
  - Bash
  - Read
triggers:
  - "organize smartvault"
  - "run smartvault organizer"
  - "process smartvault documents"
  - "smartvault skill"
  - "configure smartvault"
  - "set smartvault credentials"
  - "update smartvault config"
  - "pause smartvault"
  - "stop after this client"
  - "continue smartvault"
  - "resume smartvault"
  - "revert smartvault client"
---

# SmartVault Organizer

You are executing a multi-phase document organization workflow. Follow each phase
precisely and in order. **Never process multiple clients simultaneously.**

---

## Naming Conventions (Reference — use during AI analysis)

### Client Root Folder Format
| Client Type | Format | Example |
|-------------|--------|---------|
| Individual | `Last Name, First Name - email@example.com` | `Smith, John - john@smith.com` |
| Business | `Business Name - primary@email.com` | `ABC Holdings LLC - ceo@abc.com` |

### Required Subfolder Structure (per client vault)
```
EIN Letter
Receipts
Tax Documents
Entity Documents
Organizer
Miscellaneous
```

### File Naming Rules
| Document Type | Target Folder | Naming Pattern | Example |
|---------------|--------------|----------------|---------|
| EIN Letter | `EIN Letter` | `EIN Letter - [Entity Name] - [YYYY-MM-DD].pdf` | `EIN Letter - ABC Holdings LLC - 2024-03-15.pdf` |
| EIN Letter (no date) | `EIN Letter` | `EIN Letter - [Entity Name].pdf` | `EIN Letter - ABC Holdings LLC.pdf` |
| Receipt | `Receipts` | `Receipt - [Vendor] - [Amount] - [YYYY-MM-DD].pdf` | `Receipt - Amazon - 245.18 - 2025-04-22.pdf` |
| Tax Document | `Tax Documents` | `Tax Document - [Form Type] - [Tax Year].pdf` | `Tax Document - 1099-NEC - 2024.pdf` |
| Entity Document | `Entity Documents` | Keep original name | — |
| Organizer | `Organizer` | `Organizer - [Type] - [Tax Year] - [Client Name].pdf` | `Organizer - Personal - 2024 - John Smith.pdf` |
| Unknown / Other | `Miscellaneous` | Keep original name | — |

**Receipt note:** Preserve varied receipt formats — do not over-normalize vendor names.
Keep different layouts as-is for Claude/Claw receipt skill testing.

**Organizer types:** Personal, Business, Installment Sales (and others as found in document).

---

## /configure — Set or View Credentials

Use this at any time to inspect or update `.mcp_state/config.json` without editing the file directly.

**View current config** (secret masked):
```bash
python scripts/main.py configure
```

**Set one or more values:**
```bash
python scripts/main.py configure \
  --client-id <CLIENT_ID> \
  --client-secret <CLIENT_SECRET> \
  --email <ACCOUNT_EMAIL> \
  --redirect-uri <REDIRECT_URI> \
  --api-base <API_BASE_URL>
```

All flags are optional — only supplied flags are written. Unspecified keys are left unchanged.

| Flag | Description | Default |
|------|-------------|---------|
| `--client-id` | SmartVault OAuth application client ID | — |
| `--client-secret` | OAuth client secret | — |
| `--email` | SmartVault account login email | — |
| `--redirect-uri` | OAuth callback URL | `http://localhost:8000/oauth/callback/` |
| `--api-base` | SmartVault REST API base URL | `https://rest.smartvault.com` |

After updating credentials, re-run `auth` to obtain a fresh token:
```bash
python scripts/main.py auth
```

---

## Phase 1: Setup & Authentication

### Step 1.1 — Initialize database

```bash
python scripts/main.py init_db
```

Parse JSON output:
- If `"config_created"` key is present → the config file was just created with empty fields.
  **STOP and tell the user:**
  > "I've created `.mcp_state/config.json`. Please fill in these fields and reply when done:
  > - `client_id` — your SmartVault OAuth client ID
  > - `client_secret` — your SmartVault OAuth client secret
  > - `redirect_uri` — OAuth callback URL (default: `http://localhost:8000/oauth/callback/`)
  > - `email` — your SmartVault account login email
  > - `api_base` — API base URL (default: `https://rest.smartvault.com`)"
- Otherwise → continue.

### Step 1.2 — Check authentication

```bash
python scripts/main.py auth
```

Parse JSON output:

**Case A — `"status": "authenticated"`:** Proceed to Phase 2.

**Case B — `"status": "auth_required"`:** Show the user:
> "Please open this URL in your browser to authorize SmartVault access:
> **`<auth_url from output>`**
>
> After authorizing, you will be redirected to your callback URL. Copy the `code`
> parameter from the redirect URL and paste it here."

After user provides the code:
```bash
python scripts/main.py auth --code <CODE_FROM_USER>
```
Verify `"status": "authenticated"` before proceeding.

**Case C — `"status": "config_missing"`:** Ask the user to fill in `.mcp_state/config.json` (see Step 1.1).

---

## Phase 2: Client Sync

```bash
python scripts/main.py sync_clients
```

This fetches all FirmClient entities from SmartVault, stores them in the local database,
and classifies each as `ready` (has email + vault path) or `not_ready`.

Parse JSON output — extract `ready_client_ids` list.

Example output:
```json
{
  "status": "ok",
  "total_clients": 150,
  "ready_client_ids": ["abc123", "def456", "ghi789"]
}
```

Report to the user:
> "Sync complete. Found `total_clients` total clients. `len(ready_client_ids)` are ready for processing."

If `ready_client_ids` is empty:
```bash
python scripts/main.py generate_reports
```
Report results and **stop**.

---

## Phase 3: The Processing Loop

Process each client **one at a time**. For **each** `client_id` in `ready_client_ids`:

---

### Step 3.0 — Check pause state

At the start of each client iteration, check whether the user has requested a pause:

```bash
python scripts/main.py run_status
```

If `"run_status": "paused"` → **stop immediately** and tell the user:
> "Run is paused. X clients still remaining. Say **'continue smartvault'** when ready to resume."

Do not process any more clients until the user resumes.

---

### Step 3.1 — Stage files for this client

```bash
python scripts/main.py stage_client_files --client_id <client_id>
```

Output is a JSON array of staged files (unorganized files downloaded to a temp folder).
Files already in the 6 standard subfolders are intentionally skipped.

Example output:
```json
[
  {"file_id": 42, "local_path": "./temp_docs/<client_id>/42_ein_letter.pdf", "name": "ein_letter.pdf", "folder_path": "..."},
  {"file_id": 43, "local_path": "./temp_docs/<client_id>/43_receipt_amazon.pdf", "name": "receipt_amazon.pdf", "folder_path": "..."}
]
```

If the array is empty → skip to Step 3.4 (cleanup) then Step 3.5 (rename).

---

### Step 3.2 — AI document analysis

For **every** file in the staged list, read the file at its `local_path` using your
native document reading / vision capabilities:

```
Read: <local_path>
```

For each file, determine:

1. **Document type** — classify as one of:
   `EIN Letter` | `Receipt` | `Tax Document` | `Entity Document` | `Organizer` | `Miscellaneous`

2. **Target folder** — map type using the table above.

3. **New filename** — apply the naming pattern:
   - **EIN Letter:** Extract issuing entity/taxpayer name and issue/effective date.
     - With date: `EIN Letter - [Name] - [YYYY-MM-DD].pdf`
     - Without date: `EIN Letter - [Name].pdf`
   - **Receipt:** Extract merchant/vendor name, total charged amount (digits and decimal
     only, e.g. `245.18`, no `$`), and transaction date.
     Format: `Receipt - [Vendor] - [Amount] - [YYYY-MM-DD].pdf`
   - **Tax Document:** Extract form type (W2, 1099-NEC, 1099-INT, K1, 1065, etc.) and
     the tax year the document covers.
     Format: `Tax Document - [Form Type] - [Year].pdf`
   - **Organizer:** Extract organizer type (Personal, Business, Installment Sales, etc.)
     and tax year. Use the client's `display_name` from the DB sync.
     Format: `Organizer - [Type] - [Year] - [Client Display Name].pdf`
   - **Entity Document / Miscellaneous:** Keep the original `name` from the staged file
     entry unchanged.

Build a processing plan — a list of `{file_id, new_name, target_folder}` objects.

---

### Step 3.3 — Process each file

For **each entry** in the processing plan, run:

```bash
python scripts/main.py process_file \
  --file_id <file_id> \
  --new_name "<new_name>" \
  --target_folder "<target_folder>"
```

- On `"status": "ok"` → continue to next file.
- On `"status": "error"` → log the error and continue; do not abort.

---

### Step 3.4 — Clean up temp files

After all files for this client have been processed (regardless of per-file errors):

```bash
python scripts/main.py cleanup_temp --client_id <client_id>
```

This deletes `./temp_docs/<client_id>/` and frees disk space before the next client.

---

### Step 3.5 — Rename the client root folder

Using the client data collected during this loop iteration, determine the canonical
folder name:

**Determine client type:**
- If `type_qualifier` from DB = `"Individual"`, or the persons list has clear first/last
  names → **Individual format:** `Last Name, First Name - email`
- Otherwise (business entity, LLC, Inc., etc.) → **Business format:** `Business Name - email`

Use the `email` stored in the DB. Use the client name from DB `display_name` or from
document analysis (whichever is more accurate/complete).

```bash
python scripts/main.py rename_client \
  --client_id <client_id> \
  --format "Smith, John - john@smith.com"
```

- On `"status": "ok"` → continue to next client.
- On `"status": "error"` → log the error, continue to next client. The client will appear
  in `failed_or_unready_clients.csv`.

---

### Repeat for all clients

After completing Steps 3.0–3.5 for one client, move to the next `client_id` in the list.
Continue until all ready clients are processed or a pause is detected.

---

## Pause, Resume & Revert

### Unintentional interruptions (power failure, network drop, crash)

No action needed. Every completed file and client is persisted in the local database immediately after processing. If the run is interrupted for any reason:

1. Simply re-trigger: **"organize smartvault"** or **"continue smartvault"**
2. Claude will call `resume` to get the list of unfinished clients and continue the loop from where it left off
3. Files already moved and renamed are skipped automatically — no duplicate work

The explicit `pause` command is only needed when the user intentionally wants to stop.

---

### Pausing a run intentionally

If the user says **"pause"** or **"stop after this client"** at any point:

```bash
python scripts/main.py pause
```

Claude will finish the current client, then stop and report:
> "Run paused. X clients remaining. Say 'continue smartvault' to resume."

### Resuming a paused run

If the user says **"continue smartvault"** or **"resume smartvault"**:

```bash
python scripts/main.py resume
```

Parse `client_ids` from output and continue the Phase 3 loop from the first client in that list.

### Reverting a client

If the user says **"revert [client name or ID]"**, identify the `client_id` from the DB and run:

```bash
python scripts/main.py revert_client --client_id <client_id>
```

This will:
- Move every file back to its original vault folder with its original filename
- Rename the client root folder back to its original name
- Reset the client status to `ready` so it can be re-processed

Parse the output and report:
> "Reverted X files for [client name]. Folder rename also reverted: yes/no."

If `failed` list is non-empty, report each error.

---

## Phase 4: Reporting

After the loop completes for all clients:

```bash
python scripts/main.py generate_reports
```

Parse the output and summarize for the user:

> "**Processing complete.**
>
> | Outcome | Count |
> |---------|-------|
> | Completed | X |
> | Failed or Not Ready | Y |
>
> Reports saved:
> - `completed_clients.csv`
> - `failed_or_unready_clients.csv`"

If `failed_or_unready` > 0, offer:
> "Would you like me to display the reasons from `failed_or_unready_clients.csv`?"

If yes, read and display the file with reasons grouped by `not_ready_reason`.

---

## Error Handling Rules

| Situation | Action |
|-----------|--------|
| Auth expired mid-run | Re-run `auth`; if `auth_required`, show URL again |
| Single file download fails | Log and skip; continue to next file |
| Single `process_file` fails | Log and skip; continue to next file |
| `rename_client` fails | Log error; mark client failed; continue to next client |
| `stage_client_files` returns empty | Skip 3.2 and 3.3; still run 3.4 and 3.5 |
| Network error (5xx) | Retry once after 5 seconds; if still failing, log and continue |

**Never abort the entire run due to a single client or file failure.**

---

## SmartVault Organization Checklist

This skill addresses the following tasks automatically:

- ☑ Rename messy client folders using `Client Name - Email` format
- ☑ Confirm each folder has a clear client email identifier  
- ☑ Create or verify standard subfolders (EIN Letter, Receipts, Tax Documents, Entity Documents, Organizer, Miscellaneous)
- ☑ Move EIN letters into `EIN Letter` with standardized names
- ☑ Move receipts into `Receipts` with Vendor, Amount, and Date
- ☑ Preserve varied receipt formats for Claude/Claw skill testing
- ☑ Move tax documents into `Tax Documents` with form type and year
- ☑ Move entity docs into `Entity Documents`
- ☑ Move organizers into `Organizer` with type, year, and client name
- ☑ Flag clients with missing email or unclear name in `failed_or_unready_clients.csv`
