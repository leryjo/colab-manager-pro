#!/usr/bin/env python3
"""
Multi-Account Authentication Manager for google-colab-cli
Official repo: https://github.com/googlecolab/google-colab-cli

This tool manages multiple Google accounts by isolating:
- OAuth tokens per account
- Session metadata per account
- Client OAuth configs per account
- NOW ALSO: Dedicated venv + named screen session per account ID (to prevent collisions with public/shared venvs/screens)

Usage:
    colab-multi add joko1 --email joko1@gmail.com
    colab-multi auth joko1
    colab-multi new joko1 sesi1 --gpu T4
    colab-multi remove joko1   # This will ALSO permanently delete venv + kill screen for joko1
"""

import os
import sys
import json
import shutil
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List


class ColabMultiAuth:
    """Manages multiple Google accounts for google-colab-cli"""

    # Colab CLI config paths
    COLAB_CONFIG_DIR = Path.home() / ".config" / "colab-cli"
    COLAB_TOKEN_PATH = COLAB_CONFIG_DIR / "token.json"
    COLAB_SESSIONS_PATH = COLAB_CONFIG_DIR / "sessions.json"
    COLAB_SETTINGS_PATH = COLAB_CONFIG_DIR / "settings.json"
    COLAB_OAUTH_CONFIG = Path.home() / ".colab-cli-oauth-config.json"

    # Our multi-auth directory
    BASE_DIR = Path.home() / ".colab-multi-auth"
    ACCOUNTS_FILE = BASE_DIR / "accounts.json"

    def __init__(self):
        self.BASE_DIR.mkdir(parents=True, exist_ok=True)
        self.accounts = self._load_accounts()
        self.COLAB_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def _load_accounts(self) -> Dict:
        if self.ACCOUNTS_FILE.exists():
            with open(self.ACCOUNTS_FILE) as f:
                return json.load(f)
        return {"accounts": {}, "active": None}

    def _save_accounts(self):
        with open(self.ACCOUNTS_FILE, 'w') as f:
            json.dump(self.accounts, f, indent=2)

    def _get_account_dir(self, name: str) -> Path:
        """Get dedicated directory for an account"""
        acc_dir = self.BASE_DIR / "accounts" / name
        acc_dir.mkdir(parents=True, exist_ok=True)
        return acc_dir

    def _get_venv_dir(self, name: str) -> Path:
        """Get dedicated venv directory for an account (NEW for collision-free isolation)"""
        venv_dir = self.BASE_DIR / "venvs" / name
        venv_dir.mkdir(parents=True, exist_ok=True)
        return venv_dir

    def ensure_account_venv_and_screen(self, name: str):
        """
        NEW FEATURE: Ensure dedicated venv + screen session named exactly after (ID AKUN)
        This prevents tabrakan/collision with other public or shared venv/screen sessions.
        Venv and screen are created ONCE per account and reused for all its new sessions.
        """
        if name not in self.accounts["accounts"]:
            print(f"Error: Account '{name}' not found. Add it first.")
            return None, None

        venv_dir = self._get_venv_dir(name)
        python_bin = venv_dir / "bin" / "python"

        if not python_bin.exists():
            print(f"🛠️  Creating dedicated venv for account '{name}' at {venv_dir} ...")
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", str(venv_dir)],
                    check=True,
                    capture_output=True
                )
                # Upgrade pip (good practice)
                subprocess.run(
                    [str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
                    check=True, capture_output=True
                )
                print(f"   ✅ Venv ready. You can pip install packages inside screen -r {name}")
            except subprocess.CalledProcessError as e:
                print(f"⚠️  Warning: Could not fully create/upgrade venv: {e}")
        else:
            print(f"   ♻️  Using existing dedicated venv for '{name}'")

        # === SCREEN SESSION with exact name = ID AKUN (no collision) ===
        screen_name = name  # IMPORTANT: nama screen = ID AKUN persis seperti request user
        try:
            result = subprocess.run(
                ["screen", "-ls"],
                capture_output=True,
                text=True,
                timeout=5
            )
            screen_exists = screen_name in result.stdout
        except (subprocess.SubprocessError, FileNotFoundError):
            print("⚠️  'screen' command not found. Please install: sudo apt install -y screen")
            screen_exists = False

        if not screen_exists:
            print(f"🖥️  Starting dedicated screen '{screen_name}' (venv auto-activated inside)...")
            # Command that activates venv then gives interactive bash login shell
            activate_cmd = f"source {venv_dir}/bin/activate && exec bash --login"
            try:
                subprocess.run(
                    ["screen", "-dmS", screen_name, "bash", "-c", activate_cmd],
                    check=True
                )
                print(f"   ✅ Screen started! Attach anytime with:  screen -r {screen_name}")
                print(f"      (Inside screen your dedicated venv is already activated)")
            except subprocess.CalledProcessError:
                print(f"⚠️  Failed to start screen session '{screen_name}' (may already be running or permission issue)")
        else:
            print(f"   ♻️  Screen session '{screen_name}' is already running.")

        return venv_dir, screen_name

    def _backup_colab_config(self):
        """Backup current colab-cli config before switching"""
        if not self.COLAB_CONFIG_DIR.exists():
            return
        backup_dir = self.BASE_DIR / "backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)
        for f in self.COLAB_CONFIG_DIR.iterdir():
            if f.is_file():
                shutil.copy2(f, backup_dir / f.name)

    def add(self, name: str, email: str = None, client_oauth: str = None):
        """Register a new account"""
        if name in self.accounts["accounts"]:
            print(f"Warning:  Account '{name}' already exists. Use 'remove' first if you want to replace.")
            return

        acc_dir = self._get_account_dir(name)

        account = {
            "name": name,
            "email": email,
            "created_at": datetime.now().isoformat(),
            "last_used": None,
            "client_oauth_config": None,
            "config_dir": str(acc_dir)
        }

        if client_oauth and Path(client_oauth).exists():
            dest = acc_dir / "client_oauth_config.json"
            shutil.copy2(client_oauth, dest)
            account["client_oauth_config"] = str(dest)

        self.accounts["accounts"][name] = account
        if self.accounts["active"] is None:
            self.accounts["active"] = name
        self._save_accounts()

        print(f"✅ Success: Account '{name}' registered")
        print(f"   Config directory: {acc_dir}")
        if client_oauth:
            print(f"   OAuth config: {dest}")

    def remove(self, name: str):
        """Remove an account + PERMANENTLY delete its venv and kill its screen session"""
        if name not in self.accounts["accounts"]:
            print(f"Error: Account '{name}' not found")
            return

        # === NEW: Permanent cleanup of venv + screen (to prevent numpuk/piling up) ===
        venv_dir = self._get_venv_dir(name)
        if venv_dir.exists():
            print(f"🗑️  Permanently deleting venv for '{name}' ({venv_dir}) ...")
            shutil.rmtree(venv_dir, ignore_errors=True)

        # Kill screen session named after this account ID
        try:
            subprocess.run(
                ["screen", "-X", "-S", name, "quit"],
                capture_output=True,
                timeout=5
            )
            print(f"   ✅ Killed screen session '{name}' (if it existed)")
        except Exception:
            pass

        # Original account dir cleanup
        acc_dir = self._get_account_dir(name)
        if acc_dir.exists():
            shutil.rmtree(acc_dir)

        del self.accounts["accounts"][name]
        if self.accounts["active"] == name:
            self.accounts["active"] = next(iter(self.accounts["accounts"]), None)
        self._save_accounts()
        print(f"✅ Success: Account '{name}' removed (venv + screen also cleaned permanently)")

    # ========== SWITCH METHOD REMOVED as per user request ==========
    # The switch concept (single active account + token swapping for global state)
    # has been removed to allow showing all accounts/sessions without switching.
    # Operations now work per-account without changing a global "active" state.

    def list_accounts(self):
        """List all accounts (no more ACTIVE marker)"""
        print("\nRegistered Accounts")
        print("=" * 60)

        if not self.accounts["accounts"]:
            print("   No accounts registered yet.")
            print("   Run: colab-multi add <name> --email <email>")
            return

        for name, acc in self.accounts["accounts"].items():
            acc_dir = self._get_account_dir(name)
            has_token = "🔑" if (acc_dir / "token.json").exists() else "❌"
            has_oauth = "📄" if acc.get("client_oauth_config") else "  "
            venv_exists = "🐍" if (self._get_venv_dir(name) / "bin" / "python").exists() else "  "

            print(f"  {has_token} {has_oauth} {venv_exists} {name}")
            print(f"     Email: {acc.get('email', 'N/A')}")
            print(f"     Created: {acc.get('created_at', 'N/A')[:10]}")
            print(f"     Last Used: {acc.get('last_used', 'Never')[:19] if acc.get('last_used') else 'Never'}")
            print()

    def status(self):
        """Show current status"""
        active = self.accounts.get("active")
        print(f"Active account (legacy): {active or 'None'}")
        print(f"Accounts dir: {self.BASE_DIR}")
        print(f"Colab config: {self.COLAB_CONFIG_DIR}")

        if active:
            acc_dir = self._get_account_dir(active)
            print(f"\nActive account config:")
            print(f"  Token: {'✅' if (acc_dir / 'token.json').exists() else '❌'}")
            print(f"  Sessions: {'✅' if (acc_dir / 'sessions.json').exists() else '❌'}")
            venv_dir = self._get_venv_dir(active)
            print(f"  Venv: {'✅' if (venv_dir / 'bin' / 'python').exists() else '❌'} @ {venv_dir}")

        self.list_accounts()

    def auth(self, name: str, strategy: str = "oauth2"):
        """Run authentication flow for an account (no global switch)"""
        # We no longer do full global switch. Just ensure token for this account.
        acc_dir = self._get_account_dir(name)
        token_file = acc_dir / "token.json"

        if token_file.exists():
            # Temporarily use this account's token for auth
            if self.COLAB_TOKEN_PATH.exists():
                shutil.copy2(self.COLAB_TOKEN_PATH, self.BASE_DIR / "token.json.bak")
            shutil.copy2(token_file, self.COLAB_TOKEN_PATH)

        print(f"\n🔐 Authenticating account: {name} (strategy: {strategy})")
        print("   Opening browser / URL to login with Google...\n")

        cmd = ["colab", f"--auth={strategy}", "sessions"]

        acc = self.accounts["accounts"].get(name, {})
        if acc.get("client_oauth_config"):
            cmd.insert(1, f"--client-oauth-config={acc['client_oauth_config']}")

        result = subprocess.run(cmd)

        if self.COLAB_TOKEN_PATH.exists():
            shutil.copy2(self.COLAB_TOKEN_PATH, acc_dir / "token.json")
            # Restore previous token if existed
            bak = self.BASE_DIR / "token.json.bak"
            if bak.exists():
                shutil.copy2(bak, self.COLAB_TOKEN_PATH)
                bak.unlink()

        print(f"\n✅ Token saved for account '{name}'")
        return result.returncode

    def new_session(self, account: str, session_name: str, **kwargs):
        """Create new colab session with specific account.
        Uses per-account token without changing global active.
        """
        acc_dir = self._get_account_dir(account)
        token_file = acc_dir / "token.json"

        # Backup current token
        if self.COLAB_TOKEN_PATH.exists():
            shutil.copy2(self.COLAB_TOKEN_PATH, self.BASE_DIR / "token.json.bak")

        if token_file.exists():
            shutil.copy2(token_file, self.COLAB_TOKEN_PATH)
        else:
            if self.COLAB_TOKEN_PATH.exists():
                self.COLAB_TOKEN_PATH.unlink()

        # Setup venv + screen (still useful)
        self.ensure_account_venv_and_screen(account)

        # Build colab new command
        cmd = ["colab", "new", "-s", session_name]

        strategy = kwargs.get("auth", "oauth2")
        cmd.insert(1, f"--auth={strategy}")

        acc = self.accounts["accounts"].get(account, {})
        if acc.get("client_oauth_config"):
            cmd.insert(2, f"--client-oauth-config={acc['client_oauth_config']}")

        if kwargs.get("gpu"):
            cmd.extend(["--gpu", kwargs["gpu"]])
        if kwargs.get("tpu"):
            cmd.extend(["--tpu", kwargs["tpu"]])
        if kwargs.get("keep"):
            cmd.append("--keep")

        print(f"\n🚀 Creating session '{session_name}' on account '{account}'...")
        print(f"   Command: {' '.join(cmd)}\n")

        result = subprocess.run(cmd)

        if self.COLAB_SESSIONS_PATH.exists():
            shutil.copy2(self.COLAB_SESSIONS_PATH, acc_dir / "sessions.json")

        # Restore previous token
        bak = self.BASE_DIR / "token.json.bak"
        if bak.exists():
            shutil.copy2(bak, self.COLAB_TOKEN_PATH)
            bak.unlink()
        elif self.COLAB_TOKEN_PATH.exists():
            self.COLAB_TOKEN_PATH.unlink()

        return result.returncode

    def run_colab(self, account: str, args: List[str]):
        """Run any colab command with specific account (no global switch)"""
        acc_dir = self._get_account_dir(account)
        token_file = acc_dir / "token.json"

        if self.COLAB_TOKEN_PATH.exists():
            shutil.copy2(self.COLAB_TOKEN_PATH, self.BASE_DIR / "token.json.bak")

        if token_file.exists():
            shutil.copy2(token_file, self.COLAB_TOKEN_PATH)
        else:
            if self.COLAB_TOKEN_PATH.exists():
                self.COLAB_TOKEN_PATH.unlink()

        cmd = ["colab"] + args
        print(f"\n▶️  colab {' '.join(args)} (account: {account})")
        result = subprocess.run(cmd).returncode

        # Restore
        bak = self.BASE_DIR / "token.json.bak"
        if bak.exists():
            shutil.copy2(bak, self.COLAB_TOKEN_PATH)
            bak.unlink()
        elif self.COLAB_TOKEN_PATH.exists():
            self.COLAB_TOKEN_PATH.unlink()

        return result

    def save_current_state(self, name: str = None):
        """Save current colab config to account"""
        name = name or self.accounts.get("active")
        if not name:
            print("No active account")
            return

        acc_dir = self._get_account_dir(name)

        if self.COLAB_TOKEN_PATH.exists():
            shutil.copy2(self.COLAB_TOKEN_PATH, acc_dir / "token.json")
        if self.COLAB_SESSIONS_PATH.exists():
            shutil.copy2(self.COLAB_SESSIONS_PATH, acc_dir / "sessions.json")
        if self.COLAB_SETTINGS_PATH.exists():
            shutil.copy2(self.COLAB_SETTINGS_PATH, acc_dir / "settings.json")

        print(f"✅ Saved current state to account '{name}'")


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Account Manager for google-colab-cli (with per-account venv + screen isolation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  colab-multi add joko1 --email joko1@gmail.com
  colab-multi auth joko1
  colab-multi new joko1 sesi1 --gpu T4     # <-- Creates venv + screen named "joko1"
  colab-multi list
  colab-multi remove joko1                 # <-- Also PERMANENTLY deletes venv + kills screen "joko1"
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    add_p = subparsers.add_parser("add", help="Add/register new account")
    add_p.add_argument("name", help="Account name (e.g., joko1, joko2)")
    add_p.add_argument("--email", help="Google email")
    add_p.add_argument("--client-oauth", help="Path to client_oauth_config.json")

    rm_p = subparsers.add_parser("remove", help="Remove account (also deletes its venv + screen permanently)")
    rm_p.add_argument("name", help="Account name")

    subparsers.add_parser("list", help="List all accounts (no ACTIVE marker)")

    subparsers.add_parser("status", help="Show current status")

    auth_p = subparsers.add_parser("auth", help="Authenticate an account")
    auth_p.add_argument("name", help="Account name")
    auth_p.add_argument("--strategy", default="oauth2", choices=["oauth2", "adc"])

    new_p = subparsers.add_parser("new", help="Create new colab session (also sets up venv + screen for the account)")
    new_p.add_argument("account", help="Account name (ID AKUN)")
    new_p.add_argument("session", help="Session name")
    new_p.add_argument("--gpu", help="GPU type (T4, L4, A100, H100)")
    new_p.add_argument("--tpu", help="TPU type")
    new_p.add_argument("--keep", action="store_true", help="Keep session alive")
    new_p.add_argument("--auth", default="oauth2", choices=["oauth2", "adc"])

    run_p = subparsers.add_parser("run", help="Run colab command with account")
    run_p.add_argument("account", help="Account name")
    run_p.add_argument("args", nargs=argparse.REMAINDER, help="colab arguments")

    save_p = subparsers.add_parser("save", help="Save current colab state to account")
    save_p.add_argument("--account", help="Account name (uses active if not specified)")

    args = parser.parse_args()

    manager = ColabMultiAuth()

    if args.command == "add":
        manager.add(args.name, args.email, args.client_oauth)
    elif args.command == "remove":
        manager.remove(args.name)
    elif args.command == "list":
        manager.list_accounts()
    elif args.command == "status":
        manager.status()
    elif args.command == "auth":
        manager.auth(args.name, args.strategy)
    elif args.command == "new":
        kwargs = {"auth": args.auth}
        if args.gpu:
            kwargs["gpu"] = args.gpu
        if args.tpu:
            kwargs["tpu"] = args.tpu
        if args.keep:
            kwargs["keep"] = True
        manager.new_session(args.account, args.session, **kwargs)
    elif args.command == "run":
        manager.run_colab(args.account, args.args)
    elif args.command == "save":
        manager.save_current_state(args.account)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
