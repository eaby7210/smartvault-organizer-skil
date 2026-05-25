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

### Step 3.1 — List files for this client (no download)

```bash
python scripts/main.py stage_client_files --client_id <client_id> --list-only
```

Walks the client vault, writes file metadata to the DB, and returns a JSON array of
unorganized files. Files already in the 6 standard subfolders are intentionally skipped.
**No files are downloaded at this step.**

Example output:
```json
[
  {"file_id": 42, "name": "ein_letter.pdf", "folder_path": "..."},
  {"file_id": 43, "name": "receipt_amazon.pdf", "folder_path": "..."}
]
```

If the array is empty → skip to Step 3.5 (cleanup) then Step 3.6 (rename).

Store the full list in memory. Split it into consecutive **batches of 3** file entries.

---

### Steps 3.2 + 3.3 — Batch download, analyse, and process (3 files at a time)

Repeat the following loop for each batch of 3 (or fewer for the last batch):

**3.2a — Download the batch**

```bash
python scripts/main.py download_file_batch \
  --client_id <client_id> \
  --file-ids "<id1>,<id2>,<id3>"
```

Returns a JSON array with `file_id`, `local_path`, `name`, and `folder_path` for each
downloaded file.

**3.2b — Read and classify**

For each file returned, read it using your native document reading / vision capabilities:

```
Read: <local_path>
```

For each file, determine:

1. **Document type** — classify as one of:
   `EIN Letter` | `Receipt` | `Tax Document` | `Entity Document` | `Organizer` | `Miscellaneous`

2. **Target folder** — map type using the naming table above.

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

**3.2c — Process and immediately clean up this batch**

For each file in the batch:

```bash
python scripts/main.py process_file \
  --file_id <file_id> \
  --new_name "<new_name>" \
  --target_folder "<target_folder>"
```

- On `"status": "ok"` (including `"note": "duplicate_resolved_by_size"`) → delete the local
  temp file immediately:
  ```bash
  rm "<local_path>"
  ```
- On `"status": "duplicate_uncertain"` → the move failed because a file with the same name
  already exists at the destination, but sizes differ. Content comparison needed:

  1. Download the destination file:
     ```bash
     python scripts/main.py fetch_dest_file --dest-path "<dest_path from response>"
     ```
  2. Read the source file (still in temp from batch download) and the destination file
     at the `local_path` returned by `fetch_dest_file`.
  3. Compare document content:
     - **Same document** → confirmed duplicate; delete source and mark completed:
       ```bash
       python scripts/main.py delete_source_file \
         --file_id <file_id> \
         --new-name "<new_name>" \
         --target-folder "<target_folder>"
       ```
       Then `rm <source_local_path>` and `rm <dest_local_path>` and continue.
     - **Different documents** → genuine conflict; report to user:
       > "Conflict on **[new_name]**: a different file already exists at
       > `[target_folder]/[new_name]`.
       > — Source: [one-line description of source content]
       > — Existing: [one-line description of dest content]
       > How should I handle this?"
       Do not delete either file. Pause and wait for instruction before continuing.
- On `"status": "error"` → log the error; delete the local temp file anyway; continue.

After all files in this batch are processed and their local copies deleted, **move on to
the next batch of 3.** Do not retain the content of the files you just read — treat them
as done.

Continue until all batches are complete.

---

### Step 3.4 — Clean up empty non-standard folders

After all batches are done, check whether any non-standard folders (folders that are not
one of the 6 standard subfolders) are now empty and can be deleted:

```bash
python scripts/main.py cleanup_empty_folders --client_id <client_id>
```

Parse JSON output:

- `deleted` — list of `{name, path}` objects for folders that were empty and deleted via API.
  Report to the user: `"Removed empty folders: [names]"`
- `non_empty` — list of `{name, path, child_count}` objects for folders that still contain files.
  If this list is **not empty**, report to the user:

  > "The following non-standard folders still contain files and were not deleted:
  > [name — N file(s)] …
  > How would you like me to handle them?"

  **Pause and wait for the user's instruction before continuing to the next client.**
  Do not proceed to Step 3.5 until the user responds.

---

### Step 3.5 — Clean up temp directory

```bash
python scripts/main.py cleanup_temp --client_id <client_id>
```

This removes `./temp_docs/<client_id>/` (handles any remaining stragglers) and frees
disk space before the next client.

---

### Step 3.6 — Rename the client root folder

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

After completing Steps 3.0–3.6 for one client, move to the next `client_id` in the list.
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
| `process_file` → `duplicate_resolved_by_size` | Same-size file at dest confirmed duplicate; source deleted automatically |
| `process_file` → `duplicate_uncertain` | Download dest, read both, compare content; resolve or pause for user |
| Single `process_file` fails | Log and skip; continue to next file |
| `rename_client` fails | Log error; mark client failed; continue to next client |
| `stage_client_files` returns empty | Skip 3.2–3.4; still run 3.5 and 3.6 |
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
