#!/usr/bin/env python3
"""SmartVault Organizer - Zero-dependency CLI for document management."""

import argparse
import base64
import csv
import json
import os
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# ─── Constants ───────────────────────────────────────────────────────────────

STATE_DIR = ".mcp_state"
DB_PATH = os.path.join(STATE_DIR, "app.db")
TOKEN_PATH = os.path.join(STATE_DIR, ".token")
CONFIG_PATH = os.path.join(STATE_DIR, "config.json")
TEMP_DIR = "temp_docs"
API_BASE = "https://rest.smartvault.com"
AUTH_URL = "https://my.smartvault.com/users/secure/IntegratedApplications.aspx"

RESTRICTED_FOLDERS = {
    "EIN Letter",
    "Receipts",
    "Tax Documents",
    "Entity Documents",
    "Organizer",
    "Miscellaneous",
}

FOLDER_TYPES = {
    "EIN Letter":       "EIN Letter",
    "Receipt":          "Receipts",
    "Tax Document":     "Tax Documents",
    "Entity Document":  "Entity Documents",
    "Organizer":        "Organizer",
    "Miscellaneous":    "Miscellaneous",
}

# ─── Config & Token ──────────────────────────────────────────────────────────

def load_config():
    if not os.path.exists(CONFIG_PATH):
        _die({"error": f"Config missing. Create {CONFIG_PATH} with client_id, client_secret, redirect_uri, email, api_base."})
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_token():
    if not os.path.exists(TOKEN_PATH):
        return None
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_token(data):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def is_token_expired(token):
    exp = _parse_iso(token.get("access_token_expires_at", ""))
    return exp is None or datetime.now(timezone.utc) >= exp


def is_refresh_expired(token):
    exp = _parse_iso(token.get("refresh_token_expires_at", ""))
    return exp is None or datetime.now(timezone.utc) >= exp


def _die(payload, code=1):
    print(json.dumps(payload))
    sys.exit(code)


def _clean_err(msg):
    """Strip binary garbage and HTML from API error messages into one short sentence."""
    s = str(msg)
    # Keep only ASCII printable (0x20-0x7E), strip HTML tags
    clean, in_tag = [], False
    for ch in s:
        if ch == '<':
            in_tag = True
            continue
        if ch == '>':
            in_tag = False
            continue
        if not in_tag and 0x20 <= ord(ch) <= 0x7E:
            clean.append(ch)
    text = ' '.join(''.join(clean).split())
    # For "HTTP NNN: <garbage>RealMessage." — skip leading non-uppercase junk after colon
    if text.startswith('HTTP ') and ':' in text[:12]:
        prefix, rest = text.split(':', 1)
        rest = rest.strip()
        i = 0
        while i < len(rest) and not rest[i].isupper():
            i += 1
        rest = rest[i:].strip()
        if '.' in rest:
            rest = rest.split('.')[0] + '.'
        text = f"{prefix}: {rest}" if rest else prefix
    return text[:120] or s[:60]


# ─── DB ──────────────────────────────────────────────────────────────────────

def get_db():
    os.makedirs(STATE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


# ─── HTTP ─────────────────────────────────────────────────────────────────────

def _auth_header(token, config):
    email = config.get("email", "")
    credentials = f"{email}:{token.get('access_token', '')}"
    return "Basic " + base64.b64encode(credentials.encode()).decode()


def _base(config):
    return config.get("api_base", API_BASE).rstrip("/")


def api_get(path, token, config, params=None):
    url = _base(config) + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": _auth_header(token, config),
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:500]}")


def api_post(path, token, config, body):
    url = _base(config) + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": _auth_header(token, config),
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:500]}")


def api_get_bytes(path, token, config):
    url = _base(config) + path
    req = urllib.request.Request(url, headers={
        "Authorization": _auth_header(token, config),
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:200]}")


def api_delete(path, token, config):
    url = _base(config) + path
    req = urllib.request.Request(url, method="DELETE", headers={
        "Authorization": _auth_header(token, config),
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:500]}")


def pth_enc(path):
    return urllib.parse.quote(path, safe="/")


def _refresh_token(token, config):
    url = _base(config) + "/auto/auth/rtoken/2"
    payload = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"],
        "client_secret": config["client_secret"],
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Refresh failed: {e.read().decode()[:300]}")
    if not data.get("error", {}).get("success"):
        raise RuntimeError(f"Refresh error: {data}")
    msg = data["message"]
    now = datetime.now(timezone.utc)
    token["access_token"] = msg["access_token"]
    token["refresh_token"] = msg["refresh_token"]
    token["access_token_expires_at"] = (now + timedelta(seconds=int(msg.get("expires_in", 3600)))).isoformat()
    token["refresh_token_expires_at"] = (now + timedelta(seconds=int(msg.get("refresh_token_expires_in", 86400)))).isoformat()
    save_token(token)
    return token


def get_valid_token():
    config = load_config()
    token = load_token()
    if token is None:
        return None, config
    if not is_token_expired(token):
        return token, config
    if is_refresh_expired(token):
        return None, config
    try:
        token = _refresh_token(token, config)
        return token, config
    except Exception:
        return None, config


# ─── API pagination helpers ──────────────────────────────────────────────────

def _entity_children(path, token, config, per_page=500):
    results = []
    page = 0
    encoded = urllib.parse.quote(path, safe="/")
    while True:
        params = {"children": 1, "page": page, "per_page": per_page, "eprop": "true"}
        data = api_get(f"/nodes/entity/{encoded}", token, config, params)
        msg = data.get("message") or {}
        children = msg.get("children") or []
        results.extend(children)
        total = msg.get("total_children") or 0
        if (page + 1) * per_page >= total or not children:
            break
        page += 1
        time.sleep(0.2)
    return results


def _pth_children(path, token, config, per_page=500):
    results = []
    page = 0
    encoded = pth_enc(path)
    while True:
        params = {"children": 1, "page": page, "per_page": per_page}
        data = api_get(f"/nodes/pth/{encoded}", token, config, params)
        msg = data.get("message") or {}
        children = msg.get("children") or []
        results.extend(children)
        total = msg.get("total_children") or 0
        if (page + 1) * per_page >= total or not children:
            break
        page += 1
        time.sleep(0.2)
    return results


# ─── eprop extraction ─────────────────────────────────────────────────────────

def _extract_email(record):
    ex = record.get("entityExProperties") or {}
    sv = (ex.get("smart_vault") or {})
    client_data = (sv.get("accounting") or {}).get("client") or {}
    persons_raw = client_data.get("persons") or []
    for p in persons_raw:
        if p.get("is_primary"):
            for e in (p.get("email_addresses") or []):
                addr = (e.get("address") or "").strip()
                if addr:
                    return addr
    for p in persons_raw:
        for e in (p.get("email_addresses") or []):
            addr = (e.get("address") or "").strip()
            if addr:
                return addr
    return ""


def _extract_persons(record):
    ex = record.get("entityExProperties") or {}
    client_data = ((ex.get("smart_vault") or {}).get("accounting") or {}).get("client") or {}
    persons_raw = client_data.get("persons") or []
    out = []
    for p in persons_raw:
        names = p.get("names") or [{}]
        name = names[0] if names else {}
        emails = [(e.get("address") or "").strip() for e in (p.get("email_addresses") or []) if (e.get("address") or "").strip()]
        out.append({
            "first_name": (name.get("FirstName") or "").strip(),
            "middle_name": (name.get("MiddleName") or "").strip(),
            "last_name": (name.get("LastName") or "").strip(),
            "is_primary": bool(p.get("is_primary")),
            "emails": emails,
        })
    return out


def _extract_type_qualifier(record):
    ex = record.get("entityExProperties") or {}
    client_data = ((ex.get("smart_vault") or {}).get("accounting") or {}).get("client") or {}
    return (client_data.get("type_qualifier") or "").strip()


def _doc_id(download_uri, link_uri):
    if download_uri:
        did = download_uri.removeprefix("/files/id/Document/")
        if did:
            return did
    if link_uri and "&id=" in link_uri:
        return link_uri.split("&id=", 1)[1].split("&", 1)[0]
    return ""


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_init_db(_args):
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tokens (
            id                        INTEGER PRIMARY KEY AUTOINCREMENT,
            sv_user_id                TEXT    UNIQUE NOT NULL,
            access_token              TEXT    NOT NULL,
            refresh_token             TEXT    NOT NULL,
            access_token_expires_at   TEXT    NOT NULL,
            refresh_token_expires_at  TEXT    NOT NULL,
            email                     TEXT    NOT NULL DEFAULT '',
            created_at                TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at                TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS firms (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            account_entity_id  TEXT UNIQUE NOT NULL,
            display_name       TEXT NOT NULL DEFAULT '',
            vault_path         TEXT NOT NULL DEFAULT '',
            created_at         TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS clients (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id         TEXT UNIQUE NOT NULL,
            firm_account_id   TEXT NOT NULL DEFAULT '',
            display_name      TEXT NOT NULL DEFAULT '',
            vault_path        TEXT NOT NULL DEFAULT '',
            entity_uri        TEXT NOT NULL DEFAULT '',
            dav_uri           TEXT NOT NULL DEFAULT '',
            email             TEXT NOT NULL DEFAULT '',
            type_qualifier    TEXT NOT NULL DEFAULT '',
            persons_json      TEXT NOT NULL DEFAULT '[]',
            status            TEXT NOT NULL DEFAULT 'processing',
            not_ready_reason  TEXT NOT NULL DEFAULT '',
            created_on        TEXT NOT NULL DEFAULT '',
            modified_on       TEXT NOT NULL DEFAULT '',
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status);

        CREATE TABLE IF NOT EXISTS folders (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            client_entity_id  TEXT NOT NULL,
            name              TEXT NOT NULL,
            path              TEXT UNIQUE NOT NULL,
            parent_path       TEXT NOT NULL DEFAULT '',
            node_type         TEXT NOT NULL DEFAULT 'FolderNodeType',
            is_root           INTEGER NOT NULL DEFAULT 0,
            total_children    INTEGER NOT NULL DEFAULT 0,
            uri               TEXT NOT NULL DEFAULT '',
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_folders_client ON folders(client_entity_id);

        CREATE TABLE IF NOT EXISTS files (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            client_entity_id      TEXT    NOT NULL,
            folder_path           TEXT    NOT NULL,
            name                  TEXT    NOT NULL,
            path                  TEXT    UNIQUE NOT NULL,
            document_id           TEXT    NOT NULL DEFAULT '',
            size                  INTEGER NOT NULL DEFAULT 0,
            download_uri          TEXT    NOT NULL DEFAULT '',
            link_uri              TEXT    NOT NULL DEFAULT '',
            categorization_status TEXT    NOT NULL DEFAULT 'processing',
            local_path            TEXT    NOT NULL DEFAULT '',
            new_name              TEXT    NOT NULL DEFAULT '',
            target_folder         TEXT    NOT NULL DEFAULT '',
            original_name         TEXT    NOT NULL DEFAULT '',
            original_folder_path  TEXT    NOT NULL DEFAULT '',
            created_on            TEXT    NOT NULL DEFAULT '',
            modified_on           TEXT    NOT NULL DEFAULT '',
            created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at            TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_files_client ON files(client_entity_id);
        CREATE INDEX IF NOT EXISTS idx_files_status  ON files(categorization_status);

        CREATE TABLE IF NOT EXISTS run_state (
            id      INTEGER PRIMARY KEY CHECK (id = 1),
            status  TEXT NOT NULL DEFAULT 'idle',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT OR IGNORE INTO run_state (id, status) VALUES (1, 'idle');
    """)

    for stmt in [
        "ALTER TABLE files ADD COLUMN original_name TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE files ADD COLUMN original_folder_path TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE clients ADD COLUMN original_vault_path TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE clients ADD COLUMN original_display_name TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            conn.execute(stmt)
        except Exception:
            pass

    conn.commit()
    conn.close()

    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "client_id": "",
                "client_secret": "",
                "redirect_uri": "http://localhost:8000/oauth/callback/",
                "email": "",
                "api_base": "https://rest.smartvault.com",
            }, f, indent=2)
        print(json.dumps({"status": "ok", "db": DB_PATH, "config_created": CONFIG_PATH, "note": "Fill in credentials in config.json before running auth."}))
    else:
        print(json.dumps({"status": "ok", "db": DB_PATH}))


def cmd_configure(args):
    os.makedirs(STATE_DIR, exist_ok=True)
    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = json.load(f)

    updated = []
    if args.client_id is not None:
        config["client_id"] = args.client_id
        updated.append("client_id")
    if args.client_secret is not None:
        config["client_secret"] = args.client_secret
        updated.append("client_secret")
    if args.redirect_uri is not None:
        config["redirect_uri"] = args.redirect_uri
        updated.append("redirect_uri")
    if args.email is not None:
        config["email"] = args.email
        updated.append("email")
    if args.api_base is not None:
        config["api_base"] = args.api_base
        updated.append("api_base")

    if not updated:
        masked = dict(config)
        if masked.get("client_secret"):
            masked["client_secret"] = masked["client_secret"][:4] + "****"
        print(json.dumps({"status": "ok", "config": masked}))
        return

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

    masked = dict(config)
    if masked.get("client_secret"):
        masked["client_secret"] = masked["client_secret"][:4] + "****"
    print(json.dumps({"status": "ok", "updated": updated, "config": masked}))


def cmd_auth(args):
    os.makedirs(STATE_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        _die({"status": "config_missing", "message": f"Create {CONFIG_PATH} with client_id, client_secret, redirect_uri, email, api_base."})
    config = load_config()

    if args.code:
        url = _base(config) + "/auto/auth/dtoken/2"
        body = json.dumps({
            "grant_type": "authorization_code",
            "code": args.code,
            "client_secret": config["client_secret"],
            "client_id": config["client_id"],
            "redirect_uri": config["redirect_uri"],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            _die({"status": "error", "message": f"Token exchange failed: {e.read().decode()[:500]}"})
        if not data.get("error", {}).get("success"):
            _die({"status": "error", "message": str(data)[:500]})
        msg = data["message"]
        now = datetime.now(timezone.utc)
        token_data = {
            "sv_user_id": msg.get("id", ""),
            "access_token": msg["access_token"],
            "refresh_token": msg["refresh_token"],
            "access_token_expires_at": (now + timedelta(seconds=int(msg.get("expires_in", 3600)))).isoformat(),
            "refresh_token_expires_at": (now + timedelta(seconds=int(msg.get("refresh_token_expires_in", 86400)))).isoformat(),
            "email": config.get("email", ""),
        }
        save_token(token_data)
        print(json.dumps({"status": "authenticated", "sv_user_id": token_data["sv_user_id"]}))
        return

    token = load_token()
    if token:
        if not is_token_expired(token):
            print(json.dumps({"status": "authenticated", "sv_user_id": token.get("sv_user_id", "")}))
            return
        if not is_refresh_expired(token):
            try:
                token = _refresh_token(token, config)
                print(json.dumps({"status": "authenticated", "sv_user_id": token.get("sv_user_id", "")}))
                return
            except Exception:
                pass

    params = urllib.parse.urlencode({
        "client_id": config.get("client_id", ""),
        "response_type": "code",
        "redirect_uri": config.get("redirect_uri", ""),
    })
    _die({
        "status": "auth_required",
        "message": "Visit the auth_url, authorize, then run: python scripts/main.py auth --code <CODE>",
        "auth_url": f"{AUTH_URL}?{params}",
    }, code=2)


def cmd_sync_clients(_args):
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated. Run: python scripts/main.py auth"})

    # Resolve firm account id
    data = api_get("/nodes/entity/SmartVault.Accounting.Firm", token, config, {"children": 1, "per_page": 1})
    msg = data.get("message") or {}
    firm_children = msg.get("children") or []
    if not firm_children:
        _die({"status": "error", "message": "No firm account found under SmartVault.Accounting.Firm."})

    firm_child = firm_children[0]
    firm_account_id = firm_child.get("name", "")
    firm_dav_uri = firm_child.get("dav_uri", "")
    firm_vault_path = firm_dav_uri.removeprefix("/nodes/pth/") if firm_dav_uri else ""
    firm_display = firm_vault_path.rsplit("/", 1)[-1] if firm_vault_path else firm_account_id

    conn = get_db()
    conn.execute("""
        INSERT INTO firms (account_entity_id, display_name, vault_path, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(account_entity_id) DO UPDATE SET
            display_name=excluded.display_name, vault_path=excluded.vault_path,
            updated_at=datetime('now')
    """, (firm_account_id, firm_display, firm_vault_path))
    conn.commit()

    # Fetch all FirmClient records
    entity_path = f"SmartVault.Accounting.Firm/{firm_account_id}/SmartVault.Accounting.FirmClient"
    records = _entity_children(entity_path, token, config)

    ready_ids = []
    for record in records:
        entity_id = record.get("name", "")
        if not entity_id:
            continue
        dav_uri = record.get("dav_uri", "")
        vault_path = dav_uri.removeprefix("/nodes/pth/") if dav_uri else ""
        entity_uri = record.get("uri", "")
        created_on = record.get("createdOn", "")
        modified_on = record.get("modifiedOn", "")
        display_name = vault_path.rsplit("/", 1)[-1].strip() if vault_path else entity_id
        email = _extract_email(record)
        persons = _extract_persons(record)
        type_qualifier = _extract_type_qualifier(record)

        not_ready_reason = ""
        if not vault_path:
            status = "not_ready"
            not_ready_reason = "missing_vault_path"
        elif not email:
            status = "not_ready"
            not_ready_reason = "missing_email"
        else:
            status = "ready"
            ready_ids.append(entity_id)

        conn.execute("""
            INSERT INTO clients
                (entity_id, firm_account_id, display_name, vault_path, entity_uri,
                 dav_uri, email, type_qualifier, persons_json, status,
                 not_ready_reason, created_on, modified_on, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(entity_id) DO UPDATE SET
                display_name=excluded.display_name,
                vault_path=excluded.vault_path,
                entity_uri=excluded.entity_uri,
                dav_uri=excluded.dav_uri,
                email=excluded.email,
                type_qualifier=excluded.type_qualifier,
                persons_json=excluded.persons_json,
                status=CASE WHEN clients.status='completed' THEN 'completed' ELSE excluded.status END,
                not_ready_reason=excluded.not_ready_reason,
                modified_on=excluded.modified_on,
                updated_at=datetime('now')
        """, (entity_id, firm_account_id, display_name, vault_path, entity_uri,
              dav_uri, email, type_qualifier, json.dumps(persons),
              status, not_ready_reason, created_on, modified_on))

        if vault_path:
            parent_path = vault_path.rsplit("/", 1)[0] if "/" in vault_path else ""
            conn.execute("""
                INSERT INTO folders (client_entity_id, name, path, parent_path, node_type, is_root, updated_at)
                VALUES (?,?,?,?,'VaultNodeType',1,datetime('now'))
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name, is_root=1, updated_at=datetime('now')
            """, (entity_id, display_name, vault_path, parent_path))

    conn.commit()

    # Sync immediate subfolders for ready clients
    for entity_id in ready_ids:
        row = conn.execute("SELECT vault_path FROM clients WHERE entity_id=?", (entity_id,)).fetchone()
        if not row or not row["vault_path"]:
            continue
        vp = row["vault_path"]
        try:
            children = _pth_children(vp, token, config)
            for ch in children:
                if ch.get("nodeType") == "FileNodeType":
                    continue
                ch_uri = ch.get("uri", "")
                ch_path = ch_uri.removeprefix("/nodes/pth/") if ch_uri else ""
                if not ch_path:
                    continue
                conn.execute("""
                    INSERT INTO folders
                        (client_entity_id, name, path, parent_path, node_type, is_root, total_children, uri, updated_at)
                    VALUES (?,?,?,?,?,0,?,?,datetime('now'))
                    ON CONFLICT(path) DO UPDATE SET
                        name=excluded.name, total_children=excluded.total_children, updated_at=datetime('now')
                """, (entity_id, ch.get("name",""), ch_path, vp,
                      ch.get("nodeType","FolderNodeType"),
                      ch.get("total_children", 0), ch_uri))
            conn.commit()
        except Exception:
            pass
        time.sleep(0.1)

    conn.close()
    print(json.dumps({
        "status": "ok",
        "total_clients": len(records),
        "ready_client_ids": ready_ids,
    }))


def cmd_stage_client_files(args):
    client_id = args.client_id
    list_only = getattr(args, "list_only", False)
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated."})

    conn = get_db()
    row = conn.execute("SELECT * FROM clients WHERE entity_id=?", (client_id,)).fetchone()
    if not row:
        conn.close()
        _die({"status": "error", "message": f"Client {client_id} not found in DB."})

    vault_path = row["vault_path"]
    client_temp = os.path.join(TEMP_DIR, client_id)
    if not list_only:
        os.makedirs(client_temp, exist_ok=True)

    results = []

    def _walk(folder_path, depth=0):
        if depth > 8:
            return
        try:
            children = _pth_children(folder_path, token, config)
        except Exception:
            return
        for child in children:
            node_type = child.get("nodeType", "")
            child_name = child.get("name", "")
            if node_type == "FileNodeType":
                _stage_one(child, client_id, folder_path, client_temp, results, conn, token, config, list_only)
            elif node_type in ("FolderNodeType", "VaultNodeType", "ContainerNodeType"):
                if child_name in RESTRICTED_FOLDERS:
                    continue
                ch_uri = child.get("uri", "")
                ch_path = ch_uri.removeprefix("/nodes/pth/") if ch_uri else ""
                if ch_path:
                    time.sleep(0.1)
                    _walk(ch_path, depth + 1)

    try:
        _walk(vault_path)
    except Exception as e:
        conn.close()
        _die({"status": "error", "message": _clean_err(e)})

    conn.commit()
    conn.close()
    print(json.dumps(results))


def _stage_one(raw, client_id, folder_path, client_temp, results, conn, token, config, list_only=False):
    name = raw.get("name", "")
    uri = raw.get("uri", "")
    file_path = uri.removeprefix("/nodes/pth/") if uri else ""
    if not file_path:
        return
    download_uri = raw.get("download_uri", "")
    link_uri = raw.get("link_uri", "")
    doc_id = _doc_id(download_uri, link_uri)
    if not doc_id:
        return

    conn.execute("""
        INSERT INTO files
            (client_entity_id, folder_path, name, path, document_id, size,
             download_uri, link_uri, categorization_status,
             original_name, original_folder_path,
             created_on, modified_on, updated_at)
        VALUES (?,?,?,?,?,?,?,?,'processing',?,?,?,?,datetime('now'))
        ON CONFLICT(path) DO UPDATE SET
            document_id=excluded.document_id, size=excluded.size,
            download_uri=excluded.download_uri, link_uri=excluded.link_uri,
            modified_on=excluded.modified_on, updated_at=datetime('now')
    """, (client_id, folder_path, name, file_path, doc_id,
          int(raw.get("size") or 0), download_uri, link_uri,
          name, folder_path,
          raw.get("createdOn", ""), raw.get("modifiedOn", "")))

    db_row = conn.execute(
        "SELECT id, categorization_status FROM files WHERE path=?", (file_path,)
    ).fetchone()
    if not db_row:
        return
    if db_row["categorization_status"] == "completed":
        return

    file_db_id = db_row["id"]

    if list_only:
        results.append({
            "file_id": file_db_id,
            "name": name,
            "folder_path": folder_path,
        })
        return

    local_path = os.path.join(client_temp, f"{file_db_id}_{name}")

    try:
        encoded_doc_id = urllib.parse.quote(doc_id, safe="")
        file_bytes = api_get_bytes(f"/files/id/Document/{encoded_doc_id}", token, config)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        conn.execute("UPDATE files SET local_path=? WHERE id=?", (local_path, file_db_id))
        results.append({
            "file_id": file_db_id,
            "local_path": local_path,
            "name": name,
            "folder_path": folder_path,
        })
    except Exception as e:
        conn.execute(
            "UPDATE files SET categorization_status='failed' WHERE id=?", (file_db_id,)
        )


def cmd_download_file_batch(args):
    client_id = args.client_id
    file_ids = [int(x.strip()) for x in args.file_ids.split(",") if x.strip()]
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated."})

    conn = get_db()
    client_temp = os.path.join(TEMP_DIR, client_id)
    os.makedirs(client_temp, exist_ok=True)

    downloaded = []
    for file_id in file_ids:
        row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if not row or row["categorization_status"] == "completed":
            continue
        name = row["name"]
        doc_id = _doc_id(row["download_uri"], row["link_uri"])
        if not doc_id:
            continue
        local_path = os.path.join(client_temp, f"{file_id}_{name}")
        try:
            encoded_doc_id = urllib.parse.quote(doc_id, safe="")
            file_bytes = api_get_bytes(f"/files/id/Document/{encoded_doc_id}", token, config)
            with open(local_path, "wb") as f:
                f.write(file_bytes)
            conn.execute("UPDATE files SET local_path=? WHERE id=?", (local_path, file_id))
            downloaded.append({
                "file_id": file_id,
                "local_path": local_path,
                "name": name,
                "folder_path": row["folder_path"],
            })
        except Exception as e:
            conn.execute(
                "UPDATE files SET categorization_status='failed' WHERE id=?", (file_id,)
            )

    conn.commit()
    conn.close()
    print(json.dumps(downloaded))


def cmd_process_file(args):
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated."})

    conn = get_db()
    file_row = conn.execute("SELECT * FROM files WHERE id=?", (args.file_id,)).fetchone()
    if not file_row:
        conn.close()
        _die({"status": "error", "message": f"File id {args.file_id} not found."})

    client_row = conn.execute(
        "SELECT vault_path FROM clients WHERE entity_id=?", (file_row["client_entity_id"],)
    ).fetchone()
    if not client_row:
        conn.close()
        _die({"status": "error", "message": "Client not found for this file."})

    source_path = file_row["path"]
    vault_path = client_row["vault_path"]
    dest_path = f"{vault_path}/{args.target_folder}/{args.new_name}"

    # Ensure target subfolder exists; create via API if missing
    target_folder_path = f"{vault_path}/{args.target_folder}"
    folder_exists = conn.execute(
        "SELECT 1 FROM folders WHERE client_entity_id=? AND path=?",
        (file_row["client_entity_id"], target_folder_path)
    ).fetchone()
    if not folder_exists:
        try:
            cr = api_post(
                f"/nodes/pth/{pth_enc(vault_path)}",
                token, config,
                {"folder": {"name": args.target_folder}},
            )
            if not (cr.get("error") or {}).get("success"):
                raise RuntimeError(f"Folder create error: {cr}")
            conn.execute("""
                INSERT OR IGNORE INTO folders
                    (client_entity_id, name, path, parent_path, node_type, is_root, updated_at)
                VALUES (?,?,?,?,'FolderNodeType',0,datetime('now'))
            """, (file_row["client_entity_id"], args.target_folder,
                  target_folder_path, vault_path))
            conn.commit()
        except Exception as e:
            conn.close()
            _die({"status": "error",
                  "message": f"Could not create target folder '{args.target_folder}': {_clean_err(e)}"})

    src_folder = source_path.rsplit("/", 1)[0]
    src_filename = source_path.rsplit("/", 1)[1]
    api_path = f"/nodes/pth/{pth_enc(src_folder)}/{urllib.parse.quote(src_filename, safe='')}"
    body = {"move": {"dst_uri": f"/nodes/pth/{pth_enc(dest_path)}", "replace": "Replace"}}

    move_error = None
    try:
        result = api_post(api_path, token, config, body)
        if not (result.get("error") or {}).get("success"):
            raise RuntimeError(f"API error: {result}")
    except Exception as e:
        move_error = e

    if move_error is not None:
        # Check whether a file already exists at the destination
        dest_is_file = False
        dest_size = 0
        dest_download_uri = ""
        dest_link_uri = ""
        try:
            dest_meta = api_get(f"/nodes/pth/{pth_enc(dest_path)}", token, config)
            dest_msg = dest_meta.get("message") or {}
            if dest_msg.get("nodeType") == "FileNodeType":
                dest_is_file = True
                dest_size = int(dest_msg.get("size") or 0)
                dest_download_uri = dest_msg.get("download_uri", "")
                dest_link_uri = dest_msg.get("link_uri", "")
        except Exception:
            pass

        if dest_is_file:
            src_size = file_row["size"]
            if src_size > 0 and src_size == dest_size:
                # Same size — high confidence duplicate; delete source
                try:
                    api_delete(f"/nodes/pth/{pth_enc(source_path)}", token, config)
                    conn.execute("""
                        UPDATE files SET
                            categorization_status='completed', new_name=?, target_folder=?,
                            updated_at=datetime('now')
                        WHERE id=?
                    """, (args.new_name, args.target_folder, args.file_id))
                    conn.commit()
                    conn.close()
                    print(json.dumps({
                        "status": "ok",
                        "file_id": args.file_id,
                        "moved_to": dest_path,
                        "note": "duplicate_resolved_by_size",
                    }))
                    return
                except Exception as del_e:
                    conn.execute(
                        "UPDATE files SET categorization_status='failed', updated_at=datetime('now') WHERE id=?",
                        (args.file_id,)
                    )
                    conn.commit()
                    conn.close()
                    _die({"status": "error",
                          "message": f"Duplicate confirmed but source delete failed: {_clean_err(del_e)}"})
            else:
                # Size mismatch or unknown — need content comparison
                conn.close()
                _die({
                    "status": "duplicate_uncertain",
                    "file_id": args.file_id,
                    "source_size": src_size,
                    "dest_size": dest_size,
                    "dest_path": dest_path,
                    "dest_download_uri": dest_download_uri,
                    "dest_link_uri": dest_link_uri,
                    "message": "File exists at destination with different size; content comparison needed.",
                })
        else:
            # No file at destination — genuine move failure
            conn.execute(
                "UPDATE files SET categorization_status='failed', updated_at=datetime('now') WHERE id=?",
                (args.file_id,)
            )
            conn.commit()
            conn.close()
            _die({"status": "error", "message": _clean_err(move_error)})

    conn.execute("""
        UPDATE files SET
            categorization_status='completed', new_name=?, target_folder=?,
            updated_at=datetime('now')
        WHERE id=?
    """, (args.new_name, args.target_folder, args.file_id))
    conn.commit()
    conn.close()
    print(json.dumps({"status": "ok", "file_id": args.file_id, "moved_to": dest_path}))


def cmd_fetch_dest_file(args):
    dest_path = args.dest_path
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated."})

    try:
        meta = api_get(f"/nodes/pth/{pth_enc(dest_path)}", token, config)
        msg = meta.get("message") or {}
        if msg.get("nodeType") != "FileNodeType":
            _die({"status": "error", "message": f"No file found at: {dest_path}"})
    except Exception as e:
        _die({"status": "error", "message": f"Could not fetch metadata: {_clean_err(e)}"})

    doc_id = _doc_id(msg.get("download_uri", ""), msg.get("link_uri", ""))
    if not doc_id:
        _die({"status": "error", "message": "Could not extract document ID from destination metadata."})

    name = msg.get("name", dest_path.rsplit("/", 1)[-1])
    compare_dir = os.path.join(TEMP_DIR, "dest_compare")
    os.makedirs(compare_dir, exist_ok=True)
    local_path = os.path.join(compare_dir, f"{int(time.time())}_{name}")

    try:
        encoded_doc_id = urllib.parse.quote(doc_id, safe="")
        file_bytes = api_get_bytes(f"/files/id/Document/{encoded_doc_id}", token, config)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
    except Exception as e:
        _die({"status": "error", "message": f"Could not download destination file: {_clean_err(e)}"})

    print(json.dumps({
        "status": "ok",
        "local_path": local_path,
        "size": int(msg.get("size") or 0),
        "modified_on": msg.get("modifiedOn", ""),
        "name": name,
    }))


def cmd_delete_source_file(args):
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated."})

    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id=?", (args.file_id,)).fetchone()
    if not row:
        conn.close()
        _die({"status": "error", "message": f"File {args.file_id} not found."})

    source_path = row["path"]

    try:
        api_delete(f"/nodes/pth/{pth_enc(source_path)}", token, config)
    except Exception as e:
        conn.close()
        _die({"status": "error", "message": f"Could not delete source file: {_clean_err(e)}"})

    conn.execute("""
        UPDATE files SET
            categorization_status='completed', new_name=?, target_folder=?,
            updated_at=datetime('now')
        WHERE id=?
    """, (args.new_name, args.target_folder, args.file_id))
    conn.commit()
    conn.close()
    print(json.dumps({
        "status": "ok",
        "file_id": args.file_id,
        "note": "duplicate_resolved_by_content",
    }))


def cmd_cleanup_temp(args):
    client_temp = os.path.join(TEMP_DIR, args.client_id)
    if os.path.exists(client_temp):
        shutil.rmtree(client_temp)
        print(json.dumps({"status": "ok", "deleted": client_temp}))
    else:
        print(json.dumps({"status": "ok", "message": f"{client_temp} not found, nothing to delete"}))


def cmd_cleanup_empty_folders(args):
    client_id = args.client_id
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated."})

    conn = get_db()
    placeholders = ",".join("?" * len(RESTRICTED_FOLDERS))
    rows = conn.execute(
        f"SELECT name, path FROM folders WHERE client_entity_id=? AND is_root=0 AND name NOT IN ({placeholders})",
        (client_id, *RESTRICTED_FOLDERS),
    ).fetchall()
    conn.close()

    deleted = []
    non_empty = []

    for row in rows:
        folder_name = row["name"]
        folder_path = row["path"]
        try:
            children = _pth_children(folder_path, token, config)
            if not children:
                api_delete(f"/nodes/pth/{pth_enc(folder_path)}", token, config)
                deleted.append({"name": folder_name, "path": folder_path})
            else:
                non_empty.append({
                    "name": folder_name,
                    "path": folder_path,
                    "child_count": len(children),
                })
        except Exception as e:
            non_empty.append({
                "name": folder_name,
                "path": folder_path,
                "error": _clean_err(e),
            })
        time.sleep(0.1)

    print(json.dumps({"status": "ok", "deleted": deleted, "non_empty": non_empty}))


def cmd_rename_client(args):
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated."})

    conn = get_db()
    row = conn.execute("SELECT * FROM clients WHERE entity_id=?", (args.client_id,)).fetchone()
    if not row:
        conn.close()
        _die({"status": "error", "message": f"Client {args.client_id} not found."})

    vault_path = row["vault_path"]
    parent_path = vault_path.rsplit("/", 1)[0] if "/" in vault_path else ""
    new_folder_name = args.format
    dest_path = f"{parent_path}/{new_folder_name}" if parent_path else new_folder_name

    # preserve original state for revert (only set once)
    orig_vault = row["original_vault_path"] or vault_path
    orig_display = row["original_display_name"] or row["display_name"]

    body = {"move": {"dst_uri": f"/nodes/pth/{pth_enc(dest_path)}", "replace": "Replace"}}

    try:
        result = api_post(f"/nodes/pth/{pth_enc(vault_path)}", token, config, body)
        if not (result.get("error") or {}).get("success"):
            raise RuntimeError(f"API error: {result}")
    except Exception as e:
        conn.execute("""
            UPDATE clients SET status='failed', not_ready_reason=?, updated_at=datetime('now')
            WHERE entity_id=?
        """, (_clean_err(e), args.client_id))
        conn.commit()
        conn.close()
        _die({"status": "error", "message": _clean_err(e)})

    conn.execute("""
        UPDATE clients SET
            status='completed', display_name=?, vault_path=?,
            dav_uri=?, original_vault_path=?, original_display_name=?,
            updated_at=datetime('now')
        WHERE entity_id=?
    """, (new_folder_name, dest_path, f"/nodes/pth/{dest_path}",
          orig_vault, orig_display, args.client_id))
    conn.commit()
    conn.close()
    print(json.dumps({"status": "ok", "client_id": args.client_id, "new_vault_path": dest_path}))


def cmd_pause(_args):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO run_state (id, status, updated_at) VALUES (1, 'paused', datetime('now'))")
    conn.commit()
    conn.close()
    print(json.dumps({"status": "paused", "message": "Run will stop after the current client finishes."}))


def cmd_resume(_args):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO run_state (id, status, updated_at) VALUES (1, 'running', datetime('now'))")
    rows = conn.execute("""
        SELECT entity_id, display_name FROM clients
        WHERE status NOT IN ('completed', 'failed')
        ORDER BY display_name
    """).fetchall()
    conn.commit()
    conn.close()
    ids = [r["entity_id"] for r in rows]
    print(json.dumps({"status": "resumed", "remaining_clients": len(ids), "client_ids": ids}))


def cmd_run_status(_args):
    conn = get_db()
    state = conn.execute("SELECT status FROM run_state WHERE id=1").fetchone()
    remaining = conn.execute("""
        SELECT COUNT(*) as n FROM clients WHERE status NOT IN ('completed', 'failed')
    """).fetchone()
    conn.close()
    print(json.dumps({
        "run_status": state["status"] if state else "idle",
        "remaining_clients": remaining["n"] if remaining else 0,
    }))


def cmd_revert_client(args):
    token, config = get_valid_token()
    if token is None:
        _die({"status": "error", "message": "Not authenticated."})

    conn = get_db()
    client_row = conn.execute("SELECT * FROM clients WHERE entity_id=?", (args.client_id,)).fetchone()
    if not client_row:
        conn.close()
        _die({"status": "error", "message": f"Client {args.client_id} not found."})

    files = conn.execute("""
        SELECT * FROM files WHERE client_entity_id=? AND categorization_status='completed'
    """, (args.client_id,)).fetchall()

    reverted, failed = [], []

    for f in files:
        orig_name   = f["original_name"]   or f["name"]
        orig_folder = f["original_folder_path"] or f["folder_path"]
        current_path = f"{client_row['vault_path']}/{f['target_folder']}/{f['new_name']}"
        dest_path    = f"{orig_folder}/{orig_name}"

        src_folder   = current_path.rsplit("/", 1)[0]
        src_filename = current_path.rsplit("/", 1)[1]
        api_path = f"/nodes/pth/{pth_enc(src_folder)}/{urllib.parse.quote(src_filename, safe='')}"
        body = {"move": {"dst_uri": f"/nodes/pth/{pth_enc(dest_path)}", "replace": "Replace"}}

        try:
            result = api_post(api_path, token, config, body)
            if not (result.get("error") or {}).get("success"):
                raise RuntimeError(f"API error: {result}")
            conn.execute("""
                UPDATE files SET categorization_status='pending', new_name='', target_folder='',
                    updated_at=datetime('now')
                WHERE id=?
            """, (f["id"],))
            reverted.append(f["id"])
        except Exception as e:
            failed.append({"file_id": f["id"], "error": _clean_err(e)})

    folder_reverted = False
    orig_vault = client_row["original_vault_path"]
    if orig_vault and orig_vault != client_row["vault_path"]:
        body = {"move": {"dst_uri": f"/nodes/pth/{pth_enc(orig_vault)}", "replace": "Replace"}}
        try:
            result = api_post(f"/nodes/pth/{pth_enc(client_row['vault_path'])}", token, config, body)
            if not (result.get("error") or {}).get("success"):
                raise RuntimeError(f"API error: {result}")
            orig_name = client_row["original_display_name"] or client_row["display_name"]
            conn.execute("""
                UPDATE clients SET vault_path=?, display_name=?, dav_uri=?,
                    status='ready', updated_at=datetime('now')
                WHERE entity_id=?
            """, (orig_vault, orig_name, f"/nodes/pth/{orig_vault}", args.client_id))
            folder_reverted = True
        except Exception as e:
            failed.append({"client_folder": _clean_err(e)})
    else:
        conn.execute("""
            UPDATE clients SET status='ready', updated_at=datetime('now') WHERE entity_id=?
        """, (args.client_id,))

    conn.commit()
    conn.close()
    print(json.dumps({
        "status": "ok",
        "reverted_files": len(reverted),
        "folder_reverted": folder_reverted,
        "failed": failed,
    }))


def cmd_generate_reports(_args):
    conn = get_db()
    all_clients = conn.execute("SELECT * FROM clients ORDER BY display_name").fetchall()

    completed = []
    failed_or_unready = []

    for row in all_clients:
        d = dict(row)
        d.pop("persons_json", None)
        stats = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN categorization_status='completed' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN categorization_status='failed'    THEN 1 ELSE 0 END) as failed
            FROM files WHERE client_entity_id=?
        """, (row["entity_id"],)).fetchone()
        d["total_files"] = stats["total"] or 0
        d["completed_files"] = stats["done"] or 0
        d["failed_files"] = stats["failed"] or 0

        if row["status"] == "completed":
            completed.append(d)
        else:
            if not d.get("not_ready_reason"):
                d["not_ready_reason"] = row["status"]
            failed_or_unready.append(d)

    conn.close()

    def write_csv(path, rows):
        if not rows:
            open(path, "w", encoding="utf-8").close()
            return
        fields = list(rows[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write_csv("completed_clients.csv", completed)
    write_csv("failed_or_unready_clients.csv", failed_or_unready)
    print(json.dumps({
        "status": "ok",
        "completed": len(completed),
        "failed_or_unready": len(failed_or_unready),
        "reports": ["completed_clients.csv", "failed_or_unready_clients.csv"],
    }))


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="smartvault",
        description="SmartVault document organizer — zero-dependency CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init_db", help="Initialize SQLite DB and default config")

    cfg_p = sub.add_parser("configure", help="Set or view config values (client_id, secret, email, etc.)")
    cfg_p.add_argument("--client-id",     dest="client_id",     default=None, help="OAuth client ID")
    cfg_p.add_argument("--client-secret", dest="client_secret", default=None, help="OAuth client secret")
    cfg_p.add_argument("--redirect-uri",  dest="redirect_uri",  default=None, help="OAuth redirect URI")
    cfg_p.add_argument("--email",         dest="email",         default=None, help="SmartVault account email")
    cfg_p.add_argument("--api-base",      dest="api_base",      default=None, help="API base URL (default: https://rest.smartvault.com)")

    auth_p = sub.add_parser("auth", help="Check/obtain OAuth token")
    auth_p.add_argument("--code", default=None,
                        help="Authorization code from OAuth callback to exchange for token")

    sub.add_parser("sync_clients", help="Sync all clients from SmartVault API; output ready IDs")

    stage_p = sub.add_parser("stage_client_files",
                              help="Walk vault and record file metadata; use --list-only to skip download")
    stage_p.add_argument("--client_id", required=True)
    stage_p.add_argument("--list-only", dest="list_only", action="store_true", default=False,
                         help="Return file metadata without downloading (use download_file_batch for batched downloads)")

    batch_p = sub.add_parser("download_file_batch",
                              help="Download specific files by DB ID to temp_docs/<client_id>/")
    batch_p.add_argument("--client_id", required=True)
    batch_p.add_argument("--file-ids", dest="file_ids", required=True,
                         help="Comma-separated file DB IDs to download, e.g. '1,2,3'")

    proc_p = sub.add_parser("process_file", help="Move/rename one file via API and mark completed")
    proc_p.add_argument("--file_id",      required=True, type=int)
    proc_p.add_argument("--new_name",     required=True)
    proc_p.add_argument("--target_folder",required=True,
                        help="One of: EIN Letter, Receipts, Tax Documents, Entity Documents, Organizer, Miscellaneous")

    fetch_dest_p = sub.add_parser("fetch_dest_file",
                                   help="Download a destination file by vault path for duplicate content comparison")
    fetch_dest_p.add_argument("--dest-path", dest="dest_path", required=True,
                               help="Full vault path of the file to download")

    del_src_p = sub.add_parser("delete_source_file",
                                help="Delete source file from vault and mark DB record as completed (confirmed duplicate)")
    del_src_p.add_argument("--file_id", required=True, type=int)
    del_src_p.add_argument("--new-name", dest="new_name", required=True)
    del_src_p.add_argument("--target-folder", dest="target_folder", required=True)

    cleanup_p = sub.add_parser("cleanup_temp", help="Delete temp_docs/<client_id>/ to free disk space")
    cleanup_p.add_argument("--client_id", required=True)

    cef_p = sub.add_parser("cleanup_empty_folders",
                            help="Delete empty non-standard subfolders from client vault via API")
    cef_p.add_argument("--client_id", required=True)

    rename_p = sub.add_parser("rename_client", help="Rename client root folder in SmartVault")
    rename_p.add_argument("--client_id", required=True)
    rename_p.add_argument("--format", required=True, dest="format",
                          help="Full new folder name, e.g. 'Smith, John - john@email.com'")

    sub.add_parser("pause",      help="Pause the run after the current client finishes")
    sub.add_parser("resume",     help="Resume a paused run; outputs remaining client IDs")
    sub.add_parser("run_status", help="Show current run state (paused/running/idle) and remaining client count")

    revert_p = sub.add_parser("revert_client", help="Undo all moves and renames for one client")
    revert_p.add_argument("--client_id", required=True)

    sub.add_parser("generate_reports", help="Write completed_clients.csv and failed_or_unready_clients.csv")

    args = parser.parse_args()
    {
        "init_db":             cmd_init_db,
        "configure":           cmd_configure,
        "auth":                cmd_auth,
        "sync_clients":        cmd_sync_clients,
        "stage_client_files":   cmd_stage_client_files,
        "download_file_batch":  cmd_download_file_batch,
        "process_file":         cmd_process_file,
        "fetch_dest_file":      cmd_fetch_dest_file,
        "delete_source_file":   cmd_delete_source_file,
        "cleanup_temp":         cmd_cleanup_temp,
        "cleanup_empty_folders": cmd_cleanup_empty_folders,
        "rename_client":       cmd_rename_client,
        "pause":               cmd_pause,
        "resume":              cmd_resume,
        "run_status":          cmd_run_status,
        "revert_client":       cmd_revert_client,
        "generate_reports":    cmd_generate_reports,
    }[args.command](args)


if __name__ == "__main__":
    main()
