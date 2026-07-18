#!/usr/bin/env python3
"""
Multi-Account Authentication Manager for google-colab-cli
Official repo: https://github.com/googlecolab/google-colab-cli

This tool manages multiple Google accounts by isolating:
- OAuth tokens per account
- Session metadata per account
- Client OAuth configs per account

Usage:
    python colab_multi_auth.py add joko1 --email joko1@gmail.com
    python colab_multi_auth.py auth joko1
    python colab_multi_auth.py new joko1 colab1 --gpu T4
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
            print(f"⚠️  Account '{name}' already exists. Use 'remove' first if you want to replace.")
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

        # If client_oauth provided, copy to account dir
        if client_oauth and Path(client_oauth).exists():
            dest = acc_dir / "client_oauth_config.json"
            shutil.copy2(client_oauth, dest)
            account["client_oauth_config"] = str(dest)

        self.accounts["accounts"][name] = account
        if self.accounts["active"] is None:
            self.accounts["active"] = name
        self._save_accounts()

        print(f"✅ Account '{name}' registered")
        print(f"   Config directory: {acc_dir}")
        if client_oauth:
            print(f"   OAuth config: {dest}")

    def remove(self, name: str):
        """Remove an account"""
        if name not in self.accounts["accounts"]:
            print(f"❌ Account '{name}' not found")
            return

        acc_dir = self._get_account_dir(name)
        if acc_dir.exists():
            shutil.rmtree(acc_dir)

        del self.accounts["accounts"][name]
        if self.accounts["active"] == name:
            self.accounts["active"] = next(iter(self.accounts["accounts"]), None)
        self._save_accounts()
        print(f"✅ Account '{name}' removed")

    def switch(self, name: str) -> bool:
        """Switch to account - swaps colab-cli config files"""
        if name not in self.accounts["accounts"]:
            print(f"❌ Account '{name}' not found. Add it first with: colab-multi add {name}")
            return False

        # Backup current config
        self._backup_colab_config()

        # Save current account's state
        current = self.accounts["active"]
        if current and current != name:
            current_dir = self._get_account_dir(current)
            if self.COLAB_TOKEN_PATH.exists():
                shutil.copy2(self.COLAB_TOKEN_PATH, current_dir / "token.json")
            if self.COLAB_SESSIONS_PATH.exists():
                shutil.copy2(self.COLAB_SESSIONS_PATH, current_dir / "sessions.json")
            if self.COLAB_SETTINGS_PATH.exists():
                shutil.copy2(self.COLAB_SETTINGS_PATH, current_dir / "settings.json")
            self.accounts["accounts"][current]["last_used"] = datetime.now().isoformat()

        # Load new account's config
        acc_dir = self._get_account_dir(name)

        # Copy account config to colab-cli
        token_file = acc_dir / "token.json"
        if token_file.exists():
            shutil.copy2(token_file, self.COLAB_TOKEN_PATH)
        else:
            # Remove old token to force re-auth
            if self.COLAB_TOKEN_PATH.exists():
                self.COLAB_TOKEN_PATH.unlink()

        sessions_file = acc_dir / "sessions.json"
        if sessions_file.exists():
            shutil.copy2(sessions_file, self.COLAB_SESSIONS_PATH)
        elif self.COLAB_SESSIONS_PATH.exists():
            self.COLAB_SESSIONS_PATH.unlink()

        settings_file = acc_dir / "settings.json"
        if settings_file.exists():
            shutil.copy2(settings_file, self.COLAB_SETTINGS_PATH)

        # Handle client oauth config
        acc_config = self.accounts["accounts"][name]
        if acc_config.get("client_oauth_config") and Path(acc_config["client_oauth_config"]).exists():
            shutil.copy2(acc_config["client_oauth_config"], self.COLAB_OAUTH_CONFIG)
        elif self.COLAB_OAUTH_CONFIG.exists():
            self.COLAB_OAUTH_CONFIG.unlink()

        self.accounts["active"] = name
        self.accounts["accounts"][name]["last_used"] = datetime.now().isoformat()
        self._save_accounts()

        # Silent switch - no print to avoid confusion
        if not token_file.exists():
            print(f"⚠️  No saved token for '{name}'. Run: colab-multi auth {name}")
        return True

    def list_accounts(self):
        """List all accounts"""
        print("\n📋 Registered Accounts")
        print("=" * 60)

        if not self.accounts["accounts"]:
            print("   No accounts registered yet.")
            print("   Run: colab-multi add <name> --email <email>")
            return

        for name, acc in self.accounts["accounts"].items():
            active = " ⭐ ACTIVE" if name == self.accounts.get("active") else ""
            acc_dir = self._get_account_dir(name)
            has_token = "🔑" if (acc_dir / "token.json").exists() else "❌"
            has_oauth = "📄" if acc.get("client_oauth_config") else "  "

            print(f"  {has_token} {has_oauth} {name}{active}")
            print(f"     Email: {acc.get('email', 'N/A')}")
            print(f"     Created: {acc.get('created_at', 'N/A')[:10]}")
            print(f"     Last Used: {acc.get('last_used', 'Never')[:19] if acc.get('last_used') else 'Never'}")
            print()

    def status(self):
        """Show current status"""
        active = self.accounts.get("active")
        print(f"Active account: {active or 'None'}")
        print(f"Accounts dir: {self.BASE_DIR}")
        print(f"Colab config: {self.COLAB_CONFIG_DIR}")

        if active:
            acc_dir = self._get_account_dir(active)
            print(f"\nActive account config:")
            print(f"  Token: {'✅' if (acc_dir / 'token.json').exists() else '❌'}")
            print(f"  Sessions: {'✅' if (acc_dir / 'sessions.json').exists() else '❌'}")

        self.list_accounts()

    def auth(self, name: str, strategy: str = "oauth2"):
        """Run authentication flow for an account"""
        if not self.switch(name):
            return 1

        print(f"\n🔐 Authenticating account: {name} (strategy: {strategy})")
        print("   Opening browser / URL to login with Google...\n")

        # Trigger auth by running a command that requires it
        # The --auth flag sets the strategy
        cmd = ["colab", f"--auth={strategy}", "sessions"]

        # Check if we have a client oauth config
        acc = self.accounts["accounts"].get(name, {})
        if acc.get("client_oauth_config"):
            cmd.insert(1, f"--client-oauth-config={acc['client_oauth_config']}")

        result = subprocess.run(cmd)

        # After auth, save the new token
        if self.COLAB_TOKEN_PATH.exists():
            acc_dir = self._get_account_dir(name)
            shutil.copy2(self.COLAB_TOKEN_PATH, acc_dir / "token.json")
            print(f"\n✅ Token saved for account '{name}'")

        return result.returncode

    def new_session(self, account: str, session_name: str, **kwargs):
        """Create new colab session with specific account"""
        if not self.switch(account):
            return 1

        # Build colab new command
        cmd = ["colab", "new", "-s", session_name]

        # Add auth strategy
        strategy = kwargs.get("auth", "oauth2")
        cmd.insert(1, f"--auth={strategy}")

        # Add client oauth config if account has one
        acc = self.accounts["accounts"].get(account, {})
        if acc.get("client_oauth_config"):
            cmd.insert(2, f"--client-oauth-config={acc['client_oauth_config']}")

        # Add GPU/TPU options
        if kwargs.get("gpu"):
            cmd.extend(["--gpu", kwargs["gpu"]])
        if kwargs.get("tpu"):
            cmd.extend(["--tpu", kwargs["tpu"]])
        if kwargs.get("keep"):
            cmd.append("--keep")

        print(f"\n🚀 Creating session '{session_name}' on account '{account}'...")
        print(f"   Command: {' '.join(cmd)}\n")

        result = subprocess.run(cmd)

        # Save updated sessions
        if self.COLAB_SESSIONS_PATH.exists():
            acc_dir = self._get_account_dir(account)
            shutil.copy2(self.COLAB_SESSIONS_PATH, acc_dir / "sessions.json")

        return result.returncode

    def run_colab(self, account: str, args: List[str]):
        """Run any colab command with specific account"""
        if not self.switch(account):
            return 1

        cmd = ["colab"] + args
        print(f"\n▶️  colab {' '.join(args)} (account: {account})")
        return subprocess.run(cmd).returncode

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
        description="Multi-Account Manager for google-colab-cli",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s add joko1 --email joko1@gmail.com
  %(prog)s add joko2 --email joko2@gmail.com --client-oauth /path/to/secret.json
  %(prog)s auth joko1                    # Authenticate joko1
  %(prog)s new joko1 colab1 --gpu T4     # Create session with joko1
  %(prog)s list                          # List all accounts
  %(prog)s switch joko2                  # Switch to joko2
  %(prog)s run joko1 sessions            # Run 'colab sessions' as joko1
  %(prog)s run joko1 exec -s colab1 -- python -c "print(1)"
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Add account
    add_p = subparsers.add_parser("add", help="Add/register new account")
    add_p.add_argument("name", help="Account name (e.g., joko1, joko2)")
    add_p.add_argument("--email", help="Google email")
    add_p.add_argument("--client-oauth", help="Path to client_oauth_config.json")

    # Remove
    rm_p = subparsers.add_parser("remove", help="Remove account")
    rm_p.add_argument("name", help="Account name")

    # List
    subparsers.add_parser("list", help="List all accounts")

    # Status
    subparsers.add_parser("status", help="Show current status")

    # Auth
    auth_p = subparsers.add_parser("auth", help="Authenticate an account")
    auth_p.add_argument("name", help="Account name")
    auth_p.add_argument("--strategy", default="oauth2", choices=["oauth2", "adc"])

    # New session
    new_p = subparsers.add_parser("new", help="Create new colab session")
    new_p.add_argument("account", help="Account name")
    new_p.add_argument("session", help="Session name")
    new_p.add_argument("--gpu", help="GPU type (T4, L4, A100, H100)")
    new_p.add_argument("--tpu", help="TPU type")
    new_p.add_argument("--keep", action="store_true", help="Keep session alive")
    new_p.add_argument("--auth", default="oauth2", choices=["oauth2", "adc"])

    # Run any command
    run_p = subparsers.add_parser("run", help="Run colab command with account")
    run_p.add_argument("account", help="Account name")
    run_p.add_argument("args", nargs=argparse.REMAINDER, help="colab arguments")

    # Save state
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
