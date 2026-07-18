#!/usr/bin/env python3
"""
Colab Manager PRO - Multi-Account Dashboard v8
Fixed: Inline console (no popup), auto-reconnect SSE, colab-multi console
"""

import os
import sys
import json
import subprocess
import threading
import time
import re
import urllib.request
import urllib.parse
import ssl
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ============================================================================
# CONFIG PATHS
# ============================================================================
COLAB_CONFIG_DIR = Path.home() / ".config" / "colab-cli"
COLAB_SESSIONS_FILE = COLAB_CONFIG_DIR / "sessions.json"
MULTI_AUTH_DIR = Path.home() / ".colab-multi-auth"
ACCOUNTS_FILE = MULTI_AUTH_DIR / "accounts.json"

# In-memory cache
session_cache = {}
cache_lock = threading.Lock()

# Active console processes
console_processes = {}
console_lock = threading.Lock()

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def run_colab(cmd_args, timeout=120):
    """Run colab command and return result"""
    try:
        result = subprocess.run(
            ["colab"] + cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_colab_streaming(cmd_args):
    """Run colab command with streaming output for SSE"""
    try:
        process = subprocess.Popen(
            ["colab"] + cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        return process
    except Exception as e:
        return None


def run_colab_multi_streaming(cmd_args):
    """Run colab-multi command with streaming output for SSE.
    Uses the system wrapper at /usr/local/bin/colab-multi
    """
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        # Use the installed wrapper (more reliable)
        process = subprocess.Popen(
            ["/usr/local/bin/colab-multi"] + cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env
        )
        return process
    except Exception as e:
        print(f"Error starting colab-multi: {e}")
        return None


def read_accounts():
    """Read multi-auth accounts registry"""
    if not ACCOUNTS_FILE.exists():
        return {"accounts": {}, "active": None}
    try:
        with open(ACCOUNTS_FILE) as f:
            return json.load(f)
    except:
        return {"accounts": {}, "active": None}


def save_accounts(data):
    """Save accounts registry"""
    MULTI_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    with open(ACCOUNTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def get_account_dir(name):
    """Get account config directory"""
    return MULTI_AUTH_DIR / "accounts" / name


def parse_colab_sessions_output(stdout):
    """Parse 'colab sessions' stdout into structured data."""
    sessions = []
    if not stdout:
        return sessions

    for line in stdout.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('Usage:') or 'No active sessions' in line:
            continue

        match = re.match(
            r'\[(.+?)\]\s*(.+?)\s*\|\s*Hardware:\s*(.+?)\s*\|\s*Variant:\s*(.+)',
            line
        )
        if match:
            raw_name = match.group(1).strip()
            runtime_id = match.group(2).strip()
            hardware = match.group(3).strip()
            variant = match.group(4).strip()
            display_name = raw_name if raw_name and raw_name != "?" else runtime_id

            sessions.append({
                "name": display_name,
                "runtime_id": runtime_id,
                "hardware": hardware,
                "variant": variant,
                "status": "active",
                "url": "",
                "created_at": datetime.now().isoformat()
            })
        else:
            parts = line.split('|')
            if len(parts) >= 1:
                name_part = parts[0].strip()
                name_match = re.match(r'\[(.+?)\]', name_part)
                raw_name = name_match.group(1) if name_match else name_part.split()[0]
                display_name = raw_name if raw_name and raw_name != "?" else "unnamed"

                sessions.append({
                    "name": display_name,
                    "runtime_id": "",
                    "hardware": "N/A",
                    "variant": "N/A",
                    "status": "active",
                    "url": "",
                    "created_at": datetime.now().isoformat(),
                    "_raw": line
                })

    return sessions


def get_session_url(session_name):
    """Get notebook URL for a session."""
    result = run_colab(["url", "-s", session_name], timeout=30)
    if result["success"]:
        url = result["stdout"].strip()
        if url and url.startswith("http"):
            return url
    return None


def discover_sessions_from_cli():
    """Discover sessions by running colab sessions command directly."""
    all_sessions = []
    seen_names = set()
    accounts_data = read_accounts()

    result = run_colab(["sessions"], timeout=30)
    if result["success"] and result["stdout"]:
        cli_sessions = parse_colab_sessions_output(result["stdout"])
        active_account = accounts_data.get("active", "default")
        for s in cli_sessions:
            s["_account_source"] = active_account
            s["_discovered_from"] = "cli_active"
            url = get_session_url(s["name"])
            if url:
                s["url"] = url
            if s["name"] not in seen_names:
                seen_names.add(s["name"])
                all_sessions.append(s)

    for acc_name in accounts_data.get("accounts", {}).keys():
        if acc_name in [s.get("_account_source") for s in all_sessions]:
            continue

        acc_dir = get_account_dir(acc_name)
        token_file = acc_dir / "token.json"

        if token_file.exists():
            import shutil
            backup_token = COLAB_CONFIG_DIR / "token.json.backup"
            current_token = COLAB_CONFIG_DIR / "token.json"

            if current_token.exists():
                shutil.copy2(current_token, backup_token)

            shutil.copy2(token_file, current_token)

            try:
                result = run_colab(["sessions"], timeout=30)
                if result["success"] and result["stdout"]:
                    cli_sessions = parse_colab_sessions_output(result["stdout"])
                    for s in cli_sessions:
                        if s["name"] not in seen_names:
                            url = get_session_url(s["name"])
                            if url:
                                s["url"] = url
                            s["_account_source"] = acc_name
                            s["_discovered_from"] = "cli_account"
                            seen_names.add(s["name"])
                            all_sessions.append(s)
            finally:
                if backup_token.exists():
                    shutil.copy2(backup_token, current_token)
                    backup_token.unlink()

    all_sessions = read_sessions_json_files(all_sessions, seen_names)
    return all_sessions


def read_sessions_json_files(existing_sessions, seen_names):
    """Read sessions from all sessions.json files as fallback."""
    sessions = list(existing_sessions)

    if COLAB_SESSIONS_FILE.exists():
        try:
            with open(COLAB_SESSIONS_FILE) as f:
                data = json.load(f)

            active_account = read_accounts().get("active", "default")
            json_sessions = normalize_session_data(data, active_account)

            for s in json_sessions:
                name = s.get("name", "unknown")
                if name not in seen_names:
                    seen_names.add(name)
                    sessions.append(s)
        except Exception as e:
            print(f"Error reading global sessions.json: {e}")

    accounts_dir = MULTI_AUTH_DIR / "accounts"
    if accounts_dir.exists():
        for acc_dir in accounts_dir.iterdir():
            if not acc_dir.is_dir():
                continue
            sessions_file = acc_dir / "sessions.json"
            if sessions_file.exists():
                try:
                    with open(sessions_file) as f:
                        data = json.load(f)

                    account_name = acc_dir.name
                    json_sessions = normalize_session_data(data, account_name)

                    for s in json_sessions:
                        name = s.get("name", "unknown")
                        if name not in seen_names:
                            seen_names.add(name)
                            sessions.append(s)
                except Exception as e:
                    print(f"Error reading {sessions_file}: {e}")

    return sessions


def normalize_session_data(data, account_name):
    """Normalize various session data formats into consistent structure."""
    sessions = []

    if isinstance(data, list):
        raw_sessions = data
    elif isinstance(data, dict):
        if "sessions" in data:
            raw_sessions = data["sessions"]
        else:
            raw_sessions = [data] if data else []
    else:
        raw_sessions = []

    for s in raw_sessions:
        if not isinstance(s, dict):
            continue

        name = s.get("name") or s.get("id") or s.get("session_name", "unknown")

        sessions.append({
            "name": name,
            "runtime_id": s.get("runtime_id", ""),
            "hardware": s.get("hardware") or s.get("accelerator") or s.get("gpu", "N/A"),
            "variant": s.get("variant") or s.get("type", "N/A"),
            "status": s.get("status", "unknown"),
            "url": s.get("url") or s.get("notebook_url") or s.get("colab_url", ""),
            "created_at": s.get("created_at", datetime.now().isoformat()),
            "_account_source": account_name,
            "_discovered_from": "json_file"
        })

    return sessions


def validate_session_exists(session_name, account=None):
    """Validate that a session actually exists in colab-cli."""
    if account:
        accounts_data = read_accounts()
        if account in accounts_data.get("accounts", {}):
            acc_dir = get_account_dir(account)
            token_file = acc_dir / "token.json"
            if token_file.exists():
                import shutil
                COLAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(token_file, COLAB_CONFIG_DIR / "token.json")

    result = run_colab(["sessions"], timeout=30)
    if result["success"] and result["stdout"]:
        sessions = parse_colab_sessions_output(result["stdout"])
        return any(s["name"] == session_name for s in sessions)
    return False


def sync_sessions():
    """Sync sessions from ALL sources to cache."""
    global session_cache

    sessions = discover_sessions_from_cli()

    with cache_lock:
        old_cache = dict(session_cache)
        session_cache.clear()

        for session in sessions:
            sid = session.get("name", "unknown")
            session["_last_sync"] = datetime.now().isoformat()
            session["_stale"] = False
            session_cache[sid] = session


def get_session_status(session):
    """Determine session status with multiple validation methods."""
    status = session.get("status", "").lower()
    if status in ["active", "running", "connected"]:
        return "active"
    elif status in ["stopped", "terminated", "disconnected", "inactive"]:
        return "inactive"

    if session.get("_discovered_from") in ["cli_active", "cli_account"]:
        return "active"

    url = session.get("url", "")
    if url and url.startswith("http"):
        return "active"

    if session.get("runtime_id"):
        return "active"

    created_at = session.get("created_at", "")
    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace('Z', '+00:00').replace('+00:00', ''))
            if (datetime.now().timestamp() - created.timestamp()) < 180:
                return "active"
        except:
            pass

    return "inactive"


# Background sync thread
def background_sync():
    while True:
        try:
            sync_sessions()
        except Exception as e:
            print(f"Background sync error: {e}")
        time.sleep(5)

sync_thread = threading.Thread(target=background_sync, daemon=True)
sync_thread.start()

# ============================================================================
# WEB ROUTES
# ============================================================================

@app.route("/")
def index():
    return render_template("index.html")


# ============================================================================
# API: SESSIONS
# ============================================================================

@app.route("/api/sessions", methods=["GET"])
def api_get_sessions():
    """Get all sessions from ALL sources."""
    sync_sessions()

    account_filter = request.args.get("account")

    with cache_lock:
        sessions = []
        for sid, session in session_cache.items():
            session_account = session.get("_account_source") or session.get("account", "default")
            if account_filter and session_account != account_filter:
                continue

            # Skip sessions with unknown or empty name
            if not sid or sid.lower() == "unknown" or sid == "?":
                continue

            hardware = session.get("hardware") or session.get("accelerator") or session.get("gpu", "N/A")
            variant = session.get("variant") or session.get("type", "N/A")
            url = session.get("url") or session.get("notebook_url") or session.get("colab_url", "")

            sessions.append({
                "id": sid,
                "name": sid,
                "account": session_account,
                "status": get_session_status(session),
                "hardware": hardware,
                "variant": variant,
                "url": url,
                "runtime_id": session.get("runtime_id", ""),
                "created_at": session.get("created_at", ""),
                "last_sync": session.get("_last_sync", ""),
                "discovered_from": session.get("_discovered_from", "unknown")
            })

    active_count = len([s for s in sessions if s["status"] == "active"])
    inactive_count = len([s for s in sessions if s["status"] == "inactive"])

    return jsonify({
        "success": True,
        "count": len(sessions),
        "active": active_count,
        "inactive": inactive_count,
        "sessions": sessions
    })


@app.route("/api/sessions", methods=["POST"])
def api_create_session():
    """Create new session via colab-cli with VALIDATION and error handling."""
    data = request.json or {}

    account = data.get("account", "default")
    session_name = data.get("name") or data.get("session_name")
    gpu = data.get("gpu", "T4")
    variant = data.get("variant", "gpu")
    auto_console = data.get("auto_console", True)

    if not session_name:
        return jsonify({"success": False, "error": "Session name required"}), 400

    # Switch to correct account
    accounts = read_accounts()
    if account in accounts.get("accounts", {}):
        acc_dir = get_account_dir(account)
        token_file = acc_dir / "token.json"

        if token_file.exists():
            import shutil
            import time
            COLAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(token_file, COLAB_CONFIG_DIR / "token.json")
            time.sleep(2)  # Wait for token to be properly loaded

            accounts["active"] = account
            accounts["accounts"][account]["last_used"] = datetime.now().isoformat()
            save_accounts(accounts)
            time.sleep(1)  # Extra delay before running colab new

    # Check if session already exists in CLI
    if validate_session_exists(session_name, account):
        return jsonify({
            "success": False, 
            "error": f"Session '{session_name}' already exists. Stop it first or use a different name."
        }), 400

    # Build colab command
    cmd = ["new", "-s", session_name]
    if gpu:
        cmd.extend(["--gpu", gpu])
    if variant and variant != "gpu":
        cmd.extend(["--variant", variant])

    result = run_colab(cmd, timeout=180)

    stderr = result.get("stderr", "")
    stdout = result.get("stdout", "")

    if "TooManyAssignmentsError" in stderr or "TooManyAssignmentsError" in stdout:
        return jsonify({
            "success": False,
            "error": "GOOGLE COLAB LIMIT: Account ini sudah mencapai batas session.\n\nSolusi:\n1. Login ke https://colab.research.google.com/drive/ dengan account ini\n2. Shutdown notebook yang masih running\n3. Atau tunggu 12-24 jam untuk reset quota\n4. Atau gunakan account Google lain",
            "error_type": "TooManyAssignmentsError",
            "output": stdout,
            "stderr": stderr
        }), 429

    if "Precondition Failed" in stderr or "Precondition Failed" in stdout:
        return jsonify({
            "success": False,
            "error": "GOOGLE COLAB ERROR: Session sudah ada di server Google tapi tidak terdeteksi lokal.\n\nSolusi:\n1. Buka https://colab.research.google.com/drive/\n2. Shutdown semua notebook\n3. Tunggu 5 menit, lalu coba lagi\n4. Atau re-authenticate: colab auth login",
            "error_type": "PreconditionFailed",
            "output": stdout,
            "stderr": stderr
        }), 409

    if result["success"]:
        time.sleep(2)

        if validate_session_exists(session_name, account):
            url = get_session_url(session_name)
            sync_sessions()

            return jsonify({
                "success": True,
                "message": f"Session '{session_name}' created successfully",
                "account": account,
                "auto_console": auto_console,
                "session": {
                    "id": session_name,
                    "name": session_name,
                    "status": "active",
                    "hardware": gpu,
                    "variant": variant,
                    "url": url or ""
                },
                "output": stdout
            })
        else:
            return jsonify({
                "success": False,
                "error": "Command appeared to succeed but session not found in colab-cli. This might be a Google Colab quota issue.",
                "output": stdout,
                "stderr": stderr
            }), 500
    else:
        return jsonify({
            "success": False,
            "error": stderr or result.get("error", "Unknown error"),
            "output": stdout
        }), 500


@app.route("/api/sessions/<name>", methods=["DELETE"])
def api_stop_session(name):
    """Stop/delete session."""
    account = request.args.get("account")

    if account:
        accounts = read_accounts()
        if account in accounts.get("accounts", {}):
            acc_dir = get_account_dir(account)
            token_file = acc_dir / "token.json"
            if token_file.exists():
                import shutil
                COLAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(token_file, COLAB_CONFIG_DIR / "token.json")

    # Kill any running console process for this session
    with console_lock:
        if name in console_processes:
            try:
                console_processes[name].terminate()
            except:
                pass
            del console_processes[name]

    result = run_colab(["stop", "-s", name], timeout=60)

    with cache_lock:
        if name in session_cache:
            del session_cache[name]

    sync_sessions()

    if result["success"]:
        return jsonify({
            "success": True,
            "message": f"Session '{name}' stopped",
            "output": result["stdout"]
        })
    else:
        return jsonify({
            "success": True,
            "message": f"Session '{name}' removed from dashboard (may not exist in CLI)",
            "warning": result.get("stderr") or result.get("error", "CLI reported error")
        })


@app.route("/api/sessions/<name>/url", methods=["GET"])
def api_session_url(name):
    """Get session URL."""
    url = get_session_url(name)

    if url:
        return jsonify({"success": True, "url": url})

    with cache_lock:
        session = session_cache.get(name, {})
        url = session.get("url") or session.get("notebook_url") or ""
        if url:
            return jsonify({"success": True, "url": url})

    return jsonify({"success": False, "error": "URL not available"})


@app.route("/api/sessions/<name>/exec", methods=["POST"])
def api_exec_session(name):
    """Execute command in session via colab-cli."""
    data = request.json or {}
    command = data.get("command", "")

    if not command:
        return jsonify({"success": False, "error": "Command required"}), 400

    cmd = ["exec", "-s", name, "--"] + command.split()
    result = run_colab(cmd, timeout=60)

    return jsonify({
        "success": result["success"],
        "output": result.get("stdout", ""),
        "error": result.get("stderr", "") if not result["success"] else None
    })

# ============================================================================
# FIXED: CONSOLE STREAMING (SSE) - Uses colab-multi with keep-alive
# ============================================================================

@app.route("/api/sessions/<name>/console", methods=["POST"])
def api_start_console(name):
    """Start console using colab-multi run <account> console."""
    data = request.json or {}
    account = data.get("account")

    # Auto-detect account from cache if not provided
    if not account:
        with cache_lock:
            session = session_cache.get(name, {})
            account = session.get("_account_source") or session.get("account")

    if not account:
        return jsonify({"success": False, "error": "Account required (session account not found)"}), 400

    import time
    time.sleep(1)

    # Kill existing console process for this session
    with console_lock:
        if name in console_processes:
            try:
                console_processes[name].terminate()
                console_processes[name].wait(timeout=3)
            except:
                pass

    # Use colab-multi run <account> console
    cmd = ["run", account, "console"]
    process = run_colab_multi_streaming(cmd)

    if process is None:
        return jsonify({
            "success": False, 
            "error": "Failed to start console. Please use terminal instead: colab-multi run <account> console"
        }), 500

    with console_lock:
        console_processes[name] = process

    return jsonify({
        "success": True,
        "message": f"Console started for session '{name}' via account '{account}'",
        "session": name,
        "account": account
    })


@app.route("/api/sessions/<name>/console/stream")
def api_console_stream(name):
    """Stream console output via Server-Sent Events (SSE)."""
    def generate():
        process = None

        with console_lock:
            process = console_processes.get(name)

        if process is None:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No active console for this session'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'connected', 'message': f'Connected to console: {name}'})}\n\n"

        try:
            while True:
                # Check if process ended
                ret = process.poll()
                if ret is not None:
                    # Process ended - try to read any remaining output
                    remaining = process.stdout.read() if process.stdout else ""
                    if remaining:
                        for line in remaining.splitlines():
                            yield f"data: {json.dumps({'type': 'output', 'message': line})}\n\n"
                    yield f"data: {json.dumps({'type': 'closed', 'message': f'Console exited with code {ret}'})}\n\n"
                    break

                # Read line with timeout
                import select
                if process.stdout:
                    ready, _, _ = select.select([process.stdout], [], [], 0.5)
                    if ready:
                        line = process.stdout.readline()
                        if line:
                            yield f"data: {json.dumps({'type': 'output', 'message': line.rstrip()})}\n\n"
                        else:
                            # EOF reached
                            time.sleep(0.1)
                    else:
                        # No data available, send heartbeat to keep connection alive
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                else:
                    time.sleep(0.5)

        except GeneratorExit:
            pass
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )


@app.route("/api/sessions/<name>/console", methods=["DELETE"])
def api_stop_console(name):
    """Stop console process for a session."""
    with console_lock:
        if name in console_processes:
            try:
                console_processes[name].terminate()
                console_processes[name].wait(timeout=5)
            except:
                pass
            del console_processes[name]
            return jsonify({"success": True, "message": f"Console stopped for '{name}'"})

    return jsonify({"success": False, "error": "No active console for this session"}), 404


@app.route("/api/sessions/<name>/console/input", methods=["POST"])
def api_console_input(name):
    """Send input to console process."""
    data = request.json or {}
    input_text = data.get("input", "")

    with console_lock:
        process = console_processes.get(name)

    if process is None:
        return jsonify({"success": False, "error": "No active console"}), 404

    try:
        process.stdin.write(input_text + "\n")
        process.stdin.flush()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sessions/sync", methods=["POST"])
def api_sync_sessions():
    """Force sync with colab-cli - clears cache and rebuilds from CLI."""
    sync_sessions()
    result = run_colab(["sessions"], timeout=30)

    return jsonify({
        "success": True,
        "synced_at": datetime.now().isoformat(),
        "cached_count": len(session_cache),
        "cli_output": result.get("stdout") if result["success"] else None,
        "cli_error": result.get("stderr") if not result["success"] else None
    })

# ============================================================================
# API: ACCOUNTS
# ============================================================================

@app.route("/api/accounts", methods=["GET"])
def api_get_accounts():
    """Get all accounts."""
    accounts_data = read_accounts()

    accounts = []
    for name, acc in accounts_data.get("accounts", {}).items():
        acc_dir = get_account_dir(name)
        has_token = (acc_dir / "token.json").exists()

        with cache_lock:
            session_count = len([
                s for s in session_cache.values()
                if s.get("_account_source") == name
            ])

        accounts.append({
            "name": name,
            "email": acc.get("email", ""),
            "active": name == accounts_data.get("active"),
            "has_token": has_token,
            "session_count": session_count,
            "last_used": acc.get("last_used", ""),
            "created_at": acc.get("created_at", "")
        })

    return jsonify({
        "success": True,
        "active": accounts_data.get("active"),
        "accounts": accounts
    })


@app.route("/api/accounts", methods=["POST"])
def api_add_account():
    """Add new account."""
    data = request.json or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()

    if not name:
        return jsonify({"success": False, "error": "Account name required"}), 400

    accounts = read_accounts()

    if name in accounts["accounts"]:
        return jsonify({"success": False, "error": f"Account '{name}' already exists"}), 400

    acc_dir = get_account_dir(name)
    acc_dir.mkdir(parents=True, exist_ok=True)

    accounts["accounts"][name] = {
        "name": name,
        "email": email,
        "created_at": datetime.now().isoformat(),
        "last_used": None,
        "client_oauth_config": None,
        "config_dir": str(acc_dir)
    }

    if accounts["active"] is None:
        accounts["active"] = name

    save_accounts(accounts)

    return jsonify({
        "success": True,
        "message": f"Account '{name}' added",
        "account": name
    })


@app.route("/api/accounts/<name>", methods=["DELETE"])
def api_remove_account(name):
    """Remove account."""
    accounts = read_accounts()

    if name not in accounts["accounts"]:
        return jsonify({"success": False, "error": "Account not found"}), 404

    import shutil
    acc_dir = get_account_dir(name)
    if acc_dir.exists():
        shutil.rmtree(acc_dir)

    del accounts["accounts"][name]

    if accounts["active"] == name:
        accounts["active"] = next(iter(accounts["accounts"]), None)

    save_accounts(accounts)

    return jsonify({"success": True, "message": f"Account '{name}' removed"})


@app.route("/api/accounts/<name>/switch", methods=["POST"])
def api_switch_account(name):
    """Switch active account."""
    accounts = read_accounts()

    if name not in accounts["accounts"]:
        return jsonify({"success": False, "error": "Account not found"}), 404

    current = accounts.get("active")
    if current and current != name:
        current_dir = get_account_dir(current)
        COLAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        import shutil

        if (COLAB_CONFIG_DIR / "token.json").exists():
            shutil.copy2(COLAB_CONFIG_DIR / "token.json", current_dir / "token.json")
        if (COLAB_CONFIG_DIR / "sessions.json").exists():
            shutil.copy2(COLAB_CONFIG_DIR / "sessions.json", current_dir / "sessions.json")
        if (COLAB_CONFIG_DIR / "settings.json").exists():
            shutil.copy2(COLAB_CONFIG_DIR / "settings.json", current_dir / "settings.json")

    acc_dir = get_account_dir(name)
    import shutil

    if (acc_dir / "token.json").exists():
        shutil.copy2(acc_dir / "token.json", COLAB_CONFIG_DIR / "token.json")
    else:
        if (COLAB_CONFIG_DIR / "token.json").exists():
            (COLAB_CONFIG_DIR / "token.json").unlink()

    if (acc_dir / "sessions.json").exists():
        shutil.copy2(acc_dir / "sessions.json", COLAB_CONFIG_DIR / "sessions.json")
    elif (COLAB_CONFIG_DIR / "sessions.json").exists():
        (COLAB_CONFIG_DIR / "sessions.json").unlink()

    accounts["active"] = name
    accounts["accounts"][name]["last_used"] = datetime.now().isoformat()
    save_accounts(accounts)

    sync_sessions()

    return jsonify({
        "success": True,
        "message": f"Switched to account '{name}'",
        "active": name
    })


# ============================================================================
# API: AUTHENTICATION
# ============================================================================

@app.route("/api/accounts/<name>/auth-url", methods=["GET"])
def api_auth_url(name):
    """Generate auth URL for headless login."""
    client_id = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com"
    redirect_uri = "https://sdk.cloud.google.com/applicationdefaultauthcode.html"
    scopes = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/colaboratory"
    ]

    import urllib.parse
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "token_usage": "remote"
    }

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    return jsonify({
        "success": True,
        "account": name,
        "auth_url": auth_url
    })


@app.route("/api/accounts/<name>/exchange", methods=["POST"])
def api_exchange_code(name):
    """Exchange auth code for token."""
    data = request.json or {}
    code = data.get("code", "").strip()

    if not code:
        return jsonify({"success": False, "error": "Authorization code required"}), 400

    token_data = {
        "code": code,
        "client_id": "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
        "client_secret": "d-FL95Q19q7MQmFpd7hHD0Ty",
        "redirect_uri": "https://sdk.cloud.google.com/applicationdefaultauthcode.html",
        "grant_type": "authorization_code"
    }

    try:
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=urllib.parse.urlencode(token_data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        ctx = ssl.create_default_context()

        with urllib.request.urlopen(req, context=ctx) as resp:
            tokens = json.loads(resp.read().decode())

        from datetime import timedelta
        expires_in = tokens.get("expires_in", 3600)
        expiry = datetime.utcnow() + timedelta(seconds=expires_in)

        token_info = {
            "token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": token_data["client_id"],
            "client_secret": token_data["client_secret"],
            "scopes": [
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/cloud-platform",
                "https://www.googleapis.com/auth/colaboratory"
            ],
            "expiry": expiry.isoformat() + "Z"
        }

        acc_dir = get_account_dir(name)
        acc_dir.mkdir(parents=True, exist_ok=True)

        with open(acc_dir / "token.json", 'w') as f:
            json.dump(token_info, f, indent=2)

        COLAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(COLAB_CONFIG_DIR / "token.json", 'w') as f:
            json.dump(token_info, f, indent=2)

        return jsonify({
            "success": True,
            "account": name,
            "has_refresh_token": bool(tokens.get("refresh_token")),
            "expires_in": expires_in
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


# ============================================================================
# DEBUG ENDPOINTS
# ============================================================================

@app.route("/api/debug/sessions-raw", methods=["GET"])
def api_debug_sessions_raw():
    """Debug: Show raw colab sessions output and parsed result."""
    result = run_colab(["sessions"], timeout=30)

    parsed = parse_colab_sessions_output(result.get("stdout", ""))

    return jsonify({
        "success": True,
        "cli_success": result["success"],
        "cli_stdout": result.get("stdout", ""),
        "cli_stderr": result.get("stderr", ""),
        "parsed_count": len(parsed),
        "parsed_sessions": parsed,
        "cache_count": len(session_cache),
        "cached_sessions": [
            {"name": k, "account": v.get("_account_source"), "status": v.get("status"), "url": v.get("url", "")}
            for k, v in session_cache.items()
        ]
    })


@app.route("/api/debug/file-check", methods=["GET"])
def api_debug_file_check():
    """Debug: Check if sessions.json files exist and their content."""
    files_info = {}

    if COLAB_SESSIONS_FILE.exists():
        try:
            with open(COLAB_SESSIONS_FILE) as f:
                content = f.read()
            files_info["global_sessions.json"] = {
                "exists": True,
                "size": len(content),
                "content_preview": content[:500]
            }
        except Exception as e:
            files_info["global_sessions.json"] = {"exists": True, "error": str(e)}
    else:
        files_info["global_sessions.json"] = {"exists": False}

    accounts_dir = MULTI_AUTH_DIR / "accounts"
    if accounts_dir.exists():
        for acc_dir in accounts_dir.iterdir():
            if not acc_dir.is_dir():
                continue
            sessions_file = acc_dir / "sessions.json"
            key = f"account_{acc_dir.name}_sessions.json"
            if sessions_file.exists():
                try:
                    with open(sessions_file) as f:
                        content = f.read()
                    files_info[key] = {
                        "exists": True,
                        "size": len(content),
                        "content_preview": content[:500]
                    }
                except Exception as e:
                    files_info[key] = {"exists": True, "error": str(e)}
            else:
                files_info[key] = {"exists": False}

    return jsonify({
        "success": True,
        "files": files_info,
        "multi_auth_dir": str(MULTI_AUTH_DIR),
        "colab_config_dir": str(COLAB_CONFIG_DIR)
    })


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Colab Manager PRO v8 - Multi-Account Dashboard")
    print("=" * 60)
    print("Fixed: Inline console, auto-reconnect SSE, colab-multi")
    print("Session sync: Active (every 5 seconds)")
    print("=" * 60)

    COLAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MULTI_AUTH_DIR.mkdir(parents=True, exist_ok=True)

    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
