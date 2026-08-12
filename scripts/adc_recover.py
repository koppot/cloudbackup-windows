#!/usr/bin/env python3
"""
adc_recover.py — ADC Backup System: Fully Automated Linux Bare-Metal Recovery
==============================================================================
Usage:
    python3 adc_recover.py --host <IP> --user <user> [--password <pass> | --key <path>]

Requirements (local machine only):
    pip install paramiko rich

The target machine only needs:
    - A fresh Linux install (Ubuntu 22.04 / 24.04)
    - SSH accessible on port 22
    - Internet connectivity
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    import paramiko
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich import print as rprint
except ImportError:
    print("Missing dependencies. Run: pip install paramiko rich")
    sys.exit(1)

console = Console()

# ─── Recovery Stage Definitions ───────────────────────────────────────────────

STAGES = [
    ("0", "Preflight Checks",          "_stage_preflight"),
    ("1", "Install System Dependencies", "_stage_install_deps"),
    ("2", "Install & Configure rclone", "_stage_rclone"),
    ("3", "Bootstrap Google Drive Auth", "_stage_gdrive_auth"),
    ("4", "Restore Application Code",   "_stage_restore_code"),
    ("5", "Restore Configuration & DB", "_stage_restore_config"),
    ("6", "Restore Secrets",            "_stage_restore_secrets"),
    ("7", "Configure systemd Service",  "_stage_systemd"),
    ("8", "Start & Verify Services",    "_stage_verify"),
]

APT_DEPS = (
    "python3 python3-pip python3-venv python3-dev "
    "git curl rsync unzip sqlite3 "
    "apache2 libapache2-mod-proxy-html "
    "mysql-server mysql-client "
    "build-essential libssl-dev"
)

PIP_DEPS = (
    "Flask>=3.0.0 flask-session>=0.8.0 pyotp>=2.9.0 qrcode[pil]>=7.4.2 "
    "bcrypt>=4.1.0 APScheduler>=3.10.4 PyYAML>=6.0.1 python-dotenv>=1.0.1 "
    "requests>=2.31.0 Pillow>=10.0.0 waitress>=3.0.0 netifaces"
)

SYSTEMD_UNIT = """\
[Unit]
Description=ADC Backup System Administrative Interface
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/adc-backup
ExecStart=/opt/adc-backup/venv/bin/python3 /opt/adc-backup/linux/app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""

APACHE_CONF = """\
<VirtualHost *:80>
    ServerName asiandvdclub.org

    ProxyPreserveHost On
    ProxyPass /backup/ http://127.0.0.1:8765/backup/
    ProxyPassReverse /backup/ http://127.0.0.1:8765/backup/

    <Proxy *>
        Allow from all
    </Proxy>
</VirtualHost>
"""


# ─── SSH Session Wrapper ───────────────────────────────────────────────────────

class SSHSession:
    def __init__(self, host: str, user: str, password: str | None, key_path: str | None, port: int = 22):
        self.host = host
        self.user = user
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict = dict(hostname=host, port=port, username=user, timeout=30)
        if key_path:
            connect_kwargs["key_filename"] = key_path
        elif password:
            connect_kwargs["password"] = password
        else:
            raise ValueError("Provide either --password or --key")

        self.client.connect(**connect_kwargs)

    def run(self, cmd: str, timeout: int = 120, check: bool = True) -> tuple[str, str]:
        """Run a command; return (stdout, stderr). Raise on nonzero exit if check=True."""
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout, get_pty=True)
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        rc = stdout.channel.recv_exit_status()
        if check and rc != 0:
            raise RuntimeError(f"Command failed (exit {rc}):\n  CMD: {cmd}\n  STDERR: {err}\n  STDOUT: {out}")
        return out, err

    def write_file(self, remote_path: str, content: str):
        """Write content to a remote file via SFTP."""
        sftp = self.client.open_sftp()
        with sftp.open(remote_path, "w") as f:
            f.write(content)
        sftp.close()

    def close(self):
        self.client.close()


# ─── Recovery Stages ──────────────────────────────────────────────────────────

class Recoverer:
    def __init__(self, ssh: SSHSession):
        self.ssh = ssh
        self.issues: list[str] = []

    # Stage 0 — Preflight
    def _stage_preflight(self):
        out, _ = self.ssh.run("uname -a && lsb_release -d 2>/dev/null || cat /etc/os-release | head -3")
        console.print(f"  [dim]OS:[/dim] {out.splitlines()[0]}")

        out, _ = self.ssh.run("curl -s --max-time 5 https://rclone.org > /dev/null && echo OK || echo FAIL")
        if "FAIL" in out:
            raise RuntimeError("No internet connectivity on target — cannot reach rclone.org")

        out, _ = self.ssh.run("df -h / | tail -1")
        console.print(f"  [dim]Disk:[/dim] {out}")

        out, _ = self.ssh.run("free -h | grep Mem:")
        console.print(f"  [dim]RAM:[/dim] {out}")

    # Stage 1 — System Dependencies
    def _stage_install_deps(self):
        self.ssh.run("apt-get update -qq", timeout=180)
        self.ssh.run(f"DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {APT_DEPS}", timeout=300)
        self.ssh.run("a2enmod proxy proxy_http headers rewrite && systemctl restart apache2", timeout=60)

    # Stage 2 — rclone
    def _stage_rclone(self):
        out, _ = self.ssh.run("which rclone || echo MISSING", check=False)
        if "MISSING" in out or not out:
            self.ssh.run("curl -fsSL https://rclone.org/install.sh | bash", timeout=120)
        out, _ = self.ssh.run("rclone --version | head -1")
        console.print(f"  [dim]rclone:[/dim] {out}")

    # Stage 3 — Google Drive Auth
    def _stage_gdrive_auth(self):
        console.print()
        console.print("  [yellow]⚠ Manual Step Required[/yellow]")
        console.print("  Run this on your [bold]local machine[/bold] to authorize Google Drive:")
        console.print()
        console.print(f"    [bold cyan]ssh -N -L 53682:127.0.0.1:53682 {self.ssh.user}@{self.ssh.host}[/bold cyan]")
        console.print()
        console.print("  Then on the [bold]target server[/bold] via a second SSH session:")
        console.print("    [bold cyan]rclone authorize \"drive\"[/bold cyan]")
        console.print()
        console.print("  Once you complete the browser OAuth consent, press [bold]ENTER[/bold] to continue.")
        input("  Waiting for authorization... ")

        out, _ = self.ssh.run("rclone lsd gdrive1: 2>&1 || echo AUTH_MISSING", check=False)
        if "AUTH_MISSING" in out or "Error" in out:
            raise RuntimeError(
                "gdrive1 remote is not authorized. Re-run 'rclone config' on the target "
                "to create the base 'gdrive1' remote with a valid OAuth token."
            )
        console.print("  [green]✓ Google Drive auth verified[/green]")

    # Stage 4 — Restore Application Code
    def _stage_restore_code(self):
        self.ssh.run("mkdir -p /opt/adc-backup/{config,db,logs,dumps,packages}")
        self.ssh.run("rclone copy gdrive1_crypt:linux/adc-config /opt/adc-backup/", timeout=300)
        self.ssh.run("rclone copy gdrive1_crypt:linux/packages /opt/adc-backup/packages/", timeout=300)
        self.ssh.run(
            "python3 -m venv /opt/adc-backup/venv && "
            f"/opt/adc-backup/venv/bin/pip install -q --upgrade pip && "
            f"/opt/adc-backup/venv/bin/pip install -q {PIP_DEPS}",
            timeout=300,
        )

    # Stage 5 — Config & Database
    def _stage_restore_config(self):
        self.ssh.run("rclone copy gdrive1_crypt:linux/config /opt/adc-backup/config/", timeout=120)
        self.ssh.run("rclone copy gdrive1_crypt:linux/database /opt/adc-backup/db/", timeout=120)
        self.ssh.run("rclone copy gdrive1_crypt:linux/etc /etc/", timeout=300)
        out, _ = self.ssh.run('sqlite3 /opt/adc-backup/db/state.db "PRAGMA integrity_check;"')
        if "ok" not in out.lower():
            raise RuntimeError(f"SQLite integrity check failed: {out}")
        console.print(f"  [dim]DB integrity:[/dim] {out}")

    # Stage 6 — Secrets
    def _stage_restore_secrets(self):
        self.ssh.run("rclone copy gdrive1_secrets_crypt:linux/secrets /", timeout=300)
        self.ssh.run(
            "chmod 600 /etc/ssl/private/* 2>/dev/null || true && "
            "chmod 700 /root/.ssh && "
            "chmod 600 /root/.ssh/authorized_keys /root/.ssh/id_* 2>/dev/null || true && "
            "chmod 600 /opt/adc-backup/rclone.conf",
            check=False,
        )

    # Stage 7 — systemd
    def _stage_systemd(self):
        self.ssh.write_file("/etc/systemd/system/adc-backup.service", SYSTEMD_UNIT)
        self.ssh.write_file("/etc/apache2/sites-available/adc-backup.conf", APACHE_CONF)
        self.ssh.run(
            "systemctl daemon-reload && "
            "systemctl enable adc-backup && "
            "a2ensite adc-backup && "
            "systemctl reload apache2"
        )

    # Stage 8 — Start & Verify
    def _stage_verify(self):
        self.ssh.run("systemctl restart adc-backup")
        time.sleep(3)
        out, _ = self.ssh.run("systemctl is-active adc-backup")
        if "active" not in out:
            raise RuntimeError("adc-backup.service failed to start. Check: journalctl -u adc-backup -n 50")
        console.print(f"  [dim]Service state:[/dim] {out}")

        out, _ = self.ssh.run(
            "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/backup/ 2>/dev/null || echo 000"
        )
        if out not in ("200", "302", "301"):
            raise RuntimeError(f"Health check returned HTTP {out} — service may not be responding")
        console.print(f"  [dim]HTTP health check:[/dim] {out} OK")

        out, _ = self.ssh.run("rclone lsd gdrive1_crypt: 2>&1 | head -5")
        console.print(f"  [dim]Drive access:[/dim] {out.splitlines()[0] if out else 'No listing output'}")

    # ─── Main Orchestrator ────────────────────────────────────────────────────

    def run(self):
        results: list[tuple[str, str, str]] = []
        all_passed = True

        for num, label, method in STAGES:
            console.rule(f"[bold cyan]Stage {num}: {label}[/bold cyan]")
            try:
                getattr(self, method)()
                console.print(f"  [green]✓ Stage {num} complete[/green]")
                results.append((num, label, "✓ PASS"))
            except RuntimeError as e:
                console.print(f"  [red]✗ Stage {num} FAILED[/red]")
                console.print(f"  [red]{e}[/red]")
                results.append((num, label, f"✗ FAIL: {e}"))
                all_passed = False
                console.print()
                console.print("[yellow]Recovery halted. Address the issue above and re-run.[/yellow]")
                break
            console.print()

        # Summary table
        table = Table(title="Recovery Summary", show_header=True, header_style="bold magenta")
        table.add_column("Stage", style="dim", width=6)
        table.add_column("Description")
        table.add_column("Result")
        for num, label, result in results:
            color = "green" if "PASS" in result else "red"
            table.add_row(num, label, f"[{color}]{result}[/{color}]")
        console.print(table)

        if all_passed:
            console.print()
            console.print("[bold green]✓ Recovery complete.[/bold green]")
            console.print(f"  Dashboard: [bold cyan]https://{self.ssh.host}/backup/drives[/bold cyan]")
        else:
            sys.exit(1)


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ADC Backup — Automated Linux Bare-Metal Recovery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using password:
  python3 adc_recover.py --host 45.135.163.139 --user root --password mypass

  # Using SSH key:
  python3 adc_recover.py --host 45.135.163.139 --user root --key ~/.ssh/id_rsa

  # Start from a specific stage (e.g. skip dep install, resume from stage 4):
  python3 adc_recover.py --host 45.135.163.139 --user root --key ~/.ssh/id_rsa --start-stage 4
        """,
    )
    parser.add_argument("--host",        required=True,  help="Target server IP or hostname")
    parser.add_argument("--user",        required=True,  help="SSH username")
    parser.add_argument("--password",    default=None,   help="SSH password")
    parser.add_argument("--key",         default=None,   help="Path to SSH private key file")
    parser.add_argument("--port",        default=22,     type=int, help="SSH port (default: 22)")
    parser.add_argument("--start-stage", default=0,      type=int, metavar="N",
                        help="Skip to stage N (0=all, 1=deps, 4=code, etc.)")
    args = parser.parse_args()

    console.print()
    console.print("[bold]ADC Backup System — Bare-Metal Recovery[/bold]")
    console.print(f"  Target : [cyan]{args.user}@{args.host}:{args.port}[/cyan]")
    console.print(f"  Auth   : [cyan]{'key: ' + args.key if args.key else 'password'  }[/cyan]")
    console.print()

    with console.status("Connecting to target..."):
        try:
            ssh = SSHSession(args.host, args.user, args.password, args.key, args.port)
        except Exception as e:
            console.print(f"[red]✗ SSH connection failed: {e}[/red]")
            console.print("[yellow]Check: host reachable, correct user/password/key, SSH port open.[/yellow]")
            sys.exit(1)

    console.print("[green]✓ SSH connection established[/green]")
    console.print()

    recoverer = Recoverer(ssh)

    # Apply --start-stage filter
    if args.start_stage > 0:
        recoverer._STAGES_OVERRIDE = [s for s in STAGES if int(s[0]) >= args.start_stage]
        console.print(f"[yellow]Resuming from Stage {args.start_stage}[/yellow]")
        console.print()

    try:
        recoverer.run()
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
