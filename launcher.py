"""地址匹配系统一键启动器"""
import subprocess
import webbrowser
import time
import sys
import os
import socket
import atexit
import signal
import ctypes

_proc = None
_PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit_pid")


def _write_pid(pid):
    try:
        with open(_PID_FILE, "w") as f:
            f.write(str(pid))
    except Exception:
        pass


def _read_pid():
    try:
        with open(_PID_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _force_kill(pid):
    """直接用 Win32 TerminateProcess，不依赖外部 taskkill 命令"""
    try:
        if sys.platform == "win32":
            # 对 pid=0 的无效值做保护
            if not pid or pid <= 0:
                return
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # 打开进程句柄
            PROCESS_TERMINATE = 0x0001
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if h:
                ctypes.windll.kernel32.TerminateProcess(h, 0)
                ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        pass


def _cleanup_proc():
    """退出时强制结束 Streamlit 子进程"""
    global _proc
    if _proc and _proc.poll() is None:
        pid = _proc.pid
        try:
            # Win32 直接用 TerminateProcess，不依赖 taskkill
            _force_kill(pid)
            # 也尝试杀掉整棵进程树
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                )
        except Exception:
            pass
    # 删除 PID 文件
    try:
        os.remove(_PID_FILE)
    except Exception:
        pass


def kill_port_process(port=8501):
    """杀掉占用指定端口的残留进程"""
    # 先尝试从 PID 文件读取
    old_pid = _read_pid()
    if old_pid and old_pid > 0:
        print(f"[清理] 发现上次残留的 PID: {old_pid}")
        _force_kill(old_pid)
        time.sleep(0.5)

    # 再查端口兜底
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                if old_pid and str(old_pid) == pid:
                    continue  # 已经处理过
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", pid],
                    capture_output=True, timeout=10,
                )
                print(f"[清理] 已结束占用端口 {port} 的残留进程 (PID {pid})")
    except Exception:
        pass


def wait_for_port(host="localhost", port=8501, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def main():
    global _proc
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # atexit 清理
    atexit.register(_cleanup_proc)

    # Ctrl+C / Ctrl+Break 处理
    def _on_exit(*_):
        _cleanup_proc()
        sys.exit(0)

    signal.signal(signal.SIGINT, _on_exit)
    signal.signal(signal.SIGTERM, _on_exit)

    print("=" * 40)
    print("   地址匹配系统 - 正在启动")
    print("=" * 40)
    print(f"项目目录: {os.getcwd()}")
    print()

    # 启动前清理残留
    print("[0/3] 清理残留进程...")
    kill_port_process(8501)

    print("[1/3] 启动 Streamlit 服务...")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    _proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **kwargs,
    )
    _write_pid(_proc.pid)
    print(f"   Streamlit PID: {_proc.pid}")

    print("[2/3] 等待服务就绪...")
    if not wait_for_port():
        print()
        print("服务启动超时！")
        _cleanup_proc()
        sys.exit(1)

    print("[3/3] 打开浏览器...")
    webbrowser.open("http://localhost:8501")
    print()
    print("=" * 40)
    print("  浏览器已打开，访问 http://localhost:8501")
    print("  关闭本窗口或按 Ctrl+C 停止服务")
    print("=" * 40)
    print()

    try:
        while True:
            line = _proc.stdout.readline()
            if not line and _proc.poll() is not None:
                break
            if line:
                print(line, end="")
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        _cleanup_proc()
        print("服务已停止。")


if __name__ == "__main__":
    main()
