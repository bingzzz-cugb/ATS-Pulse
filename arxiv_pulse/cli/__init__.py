#!/usr/bin/env python3
"""
arXiv Pulse - Web 界面启动器
仅提供 serve 命令启动 Web 服务
"""

import atexit
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import click

from arxiv_pulse.__version__ import __version__
from arxiv_pulse.core import ServiceLock, check_and_acquire_lock, pid_is_alive, terminate_process


def _is_port_in_use(host: str, port: int) -> bool:
    """Check if a port is already in use"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host, port))
            return result == 0
    except Exception:
        return False


def _is_localhost(host: str) -> bool:
    """Check if host is a localhost address"""
    localhost_aliases = {"localhost", "127.0.0.1", "::1"}
    if host in localhost_aliases:
        return True
    if host.startswith("127."):
        return True
    return False


def _show_security_warning_and_confirm() -> bool:
    """Show security warning and wait for user confirmation"""
    click.echo(f"\n{'=' * 60}")
    click.secho("  ⚠️  安全警告: 您正在开放非本地访问！", fg="red", bold=True)
    click.secho("  ⚠️  Security Warning: Opening non-localhost access!", fg="red", bold=True)
    click.echo("=" * 60)
    click.echo("""
    这意味着 / This means:
    • 所有数据（包括 API Key）将以明文传输
      All data (including API Key) will be transmitted in plaintext
    • 同一网络中的任何人都可以访问您的服务（无需认证）
      Anyone on the same network can access your service (no authentication)
    • 请勿在不信任的网络中使用
      Do not use on untrusted networks

    ═══════════════════════════════════════════════════════════
    💡 推荐方式 / Recommended Approach:
    ═══════════════════════════════════════════════════════════

    在服务器上绑定 127.0.0.1，然后通过 SSH 隧道访问：
    Bind to 127.0.0.1 on server, then access via SSH tunnel:

      # 服务器上 / On server:
      pulse serve .

      # 你的电脑上 / On your computer:
      ssh -L 8000:localhost:8000 user@server

      # 然后访问 / Then visit:
      http://localhost:8000

    这样既安全又方便，无需使用本选项！
    This is both secure and convenient, no need for this option!

    ═══════════════════════════════════════════════════════════
    其他方式 / Other Options:
    ═══════════════════════════════════════════════════════════

    1. VPN:
       通过 OpenVPN/WireGuard 建立安全通道
       Establish a secure tunnel via OpenVPN/WireGuard

    2. 反向代理 / Reverse Proxy:
       使用 Nginx/Caddy 配置 HTTPS
       Configure HTTPS using Nginx/Caddy
    """)
    click.echo("=" * 60)

    response = click.prompt("是否继续 / Continue? [y/N]", default="n", show_default=False)
    return response.lower() in ("y", "yes")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="arXiv Pulse")
def cli():
    """arXiv Pulse - 智能 arXiv 文献追踪系统

    命令:
        serve/start   启动 Web 服务
        stop          停止后台服务
        restart       重启服务
        status        查看服务状态

    启动服务后访问 http://localhost:8000 进行初始化配置和使用。

    示例:
        pulse serve .              # 后台启动服务
        pulse serve . -f           # 前台运行（可看日志）
        pulse stop .               # 停止服务
        pulse status .             # 查看状态
    """
    pass


_lock_instance: ServiceLock | None = None


def _cleanup_lock():
    """Cleanup lock on exit"""
    global _lock_instance
    if _lock_instance:
        _lock_instance.release()
        _lock_instance = None


def _signal_handler(signum, frame):
    """Handle interrupt signals"""
    _cleanup_lock()
    click.echo("\n服务已停止 / Service stopped")
    sys.exit(0)


@cli.command()
@click.argument("directory", type=click.Path(exists=False, file_okay=False), default=".")
@click.option("--host", default="127.0.0.1", help="服务监听地址 (默认: 127.0.0.1)")
@click.option("--port", default=8000, type=int, help="服务监听端口 (默认: 8000)")
@click.option("--foreground", "-f", is_flag=True, help="前台运行模式（默认后台运行）")
@click.option("--force", is_flag=True, help="强制启动（忽略已有的锁）")
@click.option(
    "--allow-non-localhost-access-with-plaintext-transmission-risk",
    is_flag=True,
    help="允许绑定非 localhost 地址（会显示安全警告）",
)
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
def start(directory, host, port, foreground, force, allow_non_localhost_access_with_plaintext_transmission_risk, yes):
    """启动 Web 服务 (同 serve)

    \b
    参数:
        DIRECTORY    数据存储目录 (默认: 当前目录)

    \b
    示例:
        pulse start                          # 后台运行，端口 8000
        pulse start -f                       # 前台运行（可看实时日志）
        pulse start --port 3000              # 使用 3000 端口
        pulse start --force                  # 强制启动（忽略已有实例）

    \b
    远程访问 (有安全风险):
        pulse start --host 0.0.0.0 \\
          --allow-non-localhost-access-with-plaintext-transmission-risk -y
    """
    _do_serve(
        directory, host, port, foreground, force, allow_non_localhost_access_with_plaintext_transmission_risk, yes
    )


@cli.command()
@click.argument("directory", type=click.Path(exists=False, file_okay=False), default=".")
@click.option("--host", default="127.0.0.1", help="服务监听地址 (默认: 127.0.0.1)")
@click.option("--port", default=8000, type=int, help="服务监听端口 (默认: 8000)")
@click.option("--foreground", "-f", is_flag=True, help="前台运行模式（默认后台运行）")
@click.option("--force", is_flag=True, help="强制启动（忽略已有的锁）")
@click.option(
    "--allow-non-localhost-access-with-plaintext-transmission-risk",
    is_flag=True,
    help="允许绑定非 localhost 地址（会显示安全警告）",
)
@click.option("-y", "--yes", is_flag=True, help="跳过确认提示")
def serve(directory, host, port, foreground, force, allow_non_localhost_access_with_plaintext_transmission_risk, yes):
    """启动 Web 服务

    \b
    参数:
        DIRECTORY    数据存储目录 (默认: 当前目录)

    \b
    示例:
        pulse serve                          # 后台运行，端口 8000
        pulse serve -f                       # 前台运行（可看实时日志）
        pulse serve --port 3000              # 使用 3000 端口
        pulse serve --force                  # 强制启动（忽略已有实例）

    \b
    远程访问 (有安全风险):
        pulse serve --host 0.0.0.0 \\
          --allow-non-localhost-access-with-plaintext-transmission-risk -y
    """
    _do_serve(
        directory, host, port, foreground, force, allow_non_localhost_access_with_plaintext_transmission_risk, yes
    )


def _do_serve(directory, host, port, foreground, force, allow_non_localhost=False, skip_confirmation=False):
    global _lock_instance

    directory = Path(directory).resolve()
    data_dir = directory / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "arxiv_papers.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    if not _is_localhost(host):
        if not allow_non_localhost:
            click.echo(f"\n{'=' * 60}")
            click.secho("  ❌ 错误: 非本地访问需要明确授权", fg="red", bold=True)
            click.secho("  ❌ Error: Non-localhost access requires explicit authorization", fg="red", bold=True)
            click.echo("=" * 60)
            click.echo(f"""
    您正在尝试绑定地址: {host}
    You are trying to bind to address: {host}

    默认情况下，服务仅允许本地访问以确保安全。
    By default, the service only allows localhost access for security.

    ═══════════════════════════════════════════════════════════
    💡 推荐远程访问方式 / Recommended Remote Access Method:
    ═══════════════════════════════════════════════════════════

    在服务器上绑定 127.0.0.1，然后通过 SSH 隧道访问：
    Bind to 127.0.0.1 on server, then access via SSH tunnel:

      # 服务器上 / On server:
      pulse serve .

      # 你的电脑上 / On your computer:
      ssh -L 8000:localhost:8000 user@server

      # 然后访问 / Then visit:
      http://localhost:8000

    这样既安全又方便！
    This is both secure and convenient!

    ═══════════════════════════════════════════════════════════

    如确需开放网络访问，请使用以下选项：
    If you really need to open network access, use:
      --allow-non-localhost-access-with-plaintext-transmission-risk

    注意：这将暴露您的 API Key 等敏感信息，任何人都可以访问！
    Warning: This will expose your API Key, anyone can access!
    """)
            sys.exit(1)

        if not skip_confirmation:
            if not _show_security_warning_and_confirm():
                click.echo("\n已取消启动 / Startup cancelled")
                sys.exit(0)
        else:
            click.secho("\n⚠️  非本地访问模式 (已确认) / Non-localhost mode (confirmed)", fg="yellow")

    lock = ServiceLock(directory)
    is_locked, lock_info = lock.is_locked()

    if is_locked and not force:
        click.echo(f"\n{'=' * 50}")
        click.secho("  ⚠️  服务已在运行中 / Service already running", fg="yellow", bold=True)
        click.echo(f"{'=' * 50}\n")
        click.echo(lock.get_status_message(lock_info))
        click.echo(f"\n如需强制启动新实例，请使用 --force 参数 / Use --force to start a new instance")
        if lock_info:
            click.echo(f"或先停止当前服务 / Or stop current service: kill {lock_info.get('pid', '')}")
        sys.exit(1)

    if force and is_locked:
        click.secho(
            "\n⚠️  警告: 强制模式，将覆盖已有锁文件 / Warning: Force mode, will overwrite lock file", fg="yellow"
        )
        lock.release()

    if _is_port_in_use(host, port):
        click.echo(f"\n{'=' * 50}")
        click.secho(f"  ❌ 端口 {port} 已被占用 / Port {port} is in use", fg="red", bold=True)
        click.echo(f"{'=' * 50}\n")
        click.echo(f"请检查是否有其他服务正在使用端口 {port} / Check if another service is using port {port}")
        click.echo(f"或使用 --port 指定其他端口 / Or use --port to specify another port")
        if is_locked and lock_info:
            click.echo(
                f"\n如果这是 arXiv Pulse 的旧实例，请先停止 / If this is an old instance, stop it first: pulse stop"
            )
        sys.exit(1)

    acquired = lock.acquire(host, port, allow_non_localhost=allow_non_localhost)
    if not acquired:
        click.secho("❌ 无法获取服务锁 / Failed to acquire service lock", fg="red")
        sys.exit(1)

    _lock_instance = lock

    atexit.register(_cleanup_lock)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    click.echo(f"\n{'=' * 50}")
    click.echo("  arXiv Pulse - 智能文献追踪系统 / Smart arXiv Tracker")
    click.echo(f"{'=' * 50}")
    click.echo(f"\n📂 数据目录 / Data directory: {directory}")
    click.echo(f"🌐 Web 界面 / Web interface: http://{host}:{port}")
    click.echo(f"📚 API 文档 / API docs: http://{host}:{port}/docs")
    click.echo(f"🔄 运行模式 / Mode: {'前台运行 / Foreground' if foreground else '后台运行 / Background'}")

    if foreground:
        import uvicorn

        click.echo("\n按 Ctrl+C 停止服务 / Press Ctrl+C to stop\n")
        try:
            uvicorn.run(
                "arxiv_pulse.web.app:app",
                host=host,
                port=port,
                log_level="info",
            )
        finally:
            _cleanup_lock()
    else:
        log_file = directory / "web.log"

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "arxiv_pulse.web.app:app",
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "info",
        ]

        with open(log_file, "w") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=log,
                start_new_session=True,
                env={**os.environ, "DATABASE_URL": f"sqlite:///{directory}/data/arxiv_papers.db"},
            )

        lock.release()
        lock.acquire(host, port, pid=process.pid, allow_non_localhost=allow_non_localhost)
        _lock_instance = None

        click.echo(f"\n✅ 服务已在后台启动 / Service started in background (PID: {process.pid})")
        click.echo(f"📝 日志文件 / Log file: {log_file}")
        click.echo(f"\n💡 停止服务 / Stop: pulse stop")
        click.echo(f"   查看状态 / Status: pulse status")


@cli.command()
@click.argument("directory", type=click.Path(exists=False, file_okay=False), default=".")
def status(directory):
    """查看服务状态

    \b
    参数:
        DIRECTORY    数据存储目录 (默认: 当前目录)

    \b
    示例:
        pulse status              # 查看当前目录的服务状态
        pulse status /path/to     # 查看指定目录的服务状态
    """
    directory = Path(directory).resolve()
    lock = ServiceLock(directory)

    is_locked, info = lock.is_locked()

    click.echo(f"\n{'=' * 50}")
    click.echo("  arXiv Pulse - 服务状态 / Service Status")
    click.echo(f"{'=' * 50}\n")
    click.echo(f"📂 数据目录 / Data directory: {directory}")
    click.echo(f"🗄️  数据库 / Database: {directory}/data/arxiv_papers.db\n")

    if is_locked:
        click.secho("✅ 服务运行中 / Service running", fg="green", bold=True)
        click.echo(lock.get_status_message(info))
    else:
        click.secho("⏹️  服务未运行 / Service not running", fg="yellow")


@cli.command()
@click.argument("directory", type=click.Path(exists=False, file_okay=False), default=".")
@click.option("--force", is_flag=True, help="强制停止 (使用 SIGKILL)")
def stop(directory, force):
    """停止后台服务

    \b
    参数:
        DIRECTORY    数据存储目录 (默认: 当前目录)

    \b
    示例:
        pulse stop               # 停止当前目录的服务
        pulse stop --force       # 强制停止 (如果普通停止无效)
        pulse stop /path/to      # 停止指定目录的服务
    """
    import time

    directory = Path(directory).resolve()
    lock = ServiceLock(directory)

    is_locked, info = lock.is_locked()

    click.echo(f"\n{'=' * 50}")
    click.echo("  arXiv Pulse - 停止服务 / Stop Service")
    click.echo(f"{'=' * 50}\n")
    click.echo(f"📂 数据目录 / Data directory: {directory}")

    if not is_locked:
        click.secho("\n⏹️  没有运行中的服务 / No service running", fg="yellow")
        return

    if info:
        pid = info.get("pid")
        host = info.get("host", "unknown")
        port = info.get("port", "unknown")

        click.echo(f"🔍 发现运行中的服务 / Found running service: http://{host}:{port} (PID: {pid})")

        sig_name = "SIGKILL" if force else "SIGTERM"
        if terminate_process(pid, force):
            click.echo(f"📤 已发送 {sig_name} 信号 / Sent {sig_name} signal...")

        for _ in range(10):
            if not pid_is_alive(pid):
                break
            time.sleep(0.5)

        if pid_is_alive(pid):
            if not force:
                click.secho("\n⚠️  进程未响应，尝试强制停止 / Process not responding, forcing stop...", fg="yellow")
                terminate_process(pid, force=True)
                time.sleep(1)

        lock.release()
        click.secho("\n✅ 服务已停止 / Service stopped", fg="green", bold=True)
    else:
        lock.release()
        click.secho("\n✅ 已清理锁文件 / Lock file cleaned", fg="green")


@cli.command()
@click.argument("directory", type=click.Path(exists=False, file_okay=False), default=".")
@click.option("--foreground", "-f", is_flag=True, help="前台运行模式（默认后台运行）")
@click.option("--force", is_flag=True, help="强制停止并重启")
def restart(directory, foreground, force):
    """重启服务

    \b
    参数:
        DIRECTORY    数据存储目录 (默认: 当前目录)

    \b
    说明:
        重启服务会使用之前的 host 和 port 配置。
        如果服务未运行，则直接启动。

    \b
    示例:
        pulse restart             # 重启服务 (后台运行)
        pulse restart -f          # 前台运行
        pulse restart --force     # 强制重启 (忽略停止失败)
    """
    import time

    directory = Path(directory).resolve()
    lock = ServiceLock(directory)

    is_locked, info = lock.is_locked()

    click.echo(f"\n{'=' * 50}")
    click.echo("  arXiv Pulse - 重启服务 / Restart Service")
    click.echo(f"{'=' * 50}\n")
    click.echo(f"📂 数据目录 / Data directory: {directory}")

    prev_host = info.get("host", "127.0.0.1") if info else "127.0.0.1"
    prev_port = info.get("port", 8000) if info else 8000
    prev_allow_non_localhost = info.get("allow_non_localhost", False) if info else False

    if is_locked and info:
        pid = info.get("pid")
        click.echo(f"🔍 发现运行中的服务 / Found running service: http://{prev_host}:{prev_port} (PID: {pid})")

        click.echo("📤 正在停止服务 / Stopping service...")
        terminate_process(pid, force)

        for _ in range(10):
            if not pid_is_alive(pid):
                break
            time.sleep(0.5)

        if pid_is_alive(pid):
            if not force:
                click.echo("⚠️  进程未响应，尝试强制停止 / Process not responding, forcing stop...")
                terminate_process(pid, force=True)
                time.sleep(1)

        lock.release()
        click.echo("✅ 旧服务已停止 / Old service stopped")

        # On Windows TerminateProcess is async: PID state flips to dead but the
        # listening socket is released only after process cleanup, so poll the
        # port to avoid a false "port in use" error on the fresh start.
        for _ in range(40):
            if not _is_port_in_use(prev_host, prev_port):
                break
            time.sleep(0.25)
    else:
        click.echo("⏹️  服务未运行 / Service not running")

    click.echo("\n🚀 正在启动新服务 / Starting new service...")
    _do_serve(
        str(directory),
        prev_host,
        prev_port,
        foreground,
        False,
        prev_allow_non_localhost,
        skip_confirmation=prev_allow_non_localhost,
    )


if __name__ == "__main__":
    cli()
