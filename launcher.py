"""地址匹配系统一键启动器"""
import subprocess
import webbrowser
import time
import sys
import os
import socket
import atexit
import signal

# 全局变量保存子进程引用，供 atexit 清理
_proc = None


def _cleanup_proc():
    """退出时强制结束 Streamlit 子进程及其子进程树"""
    global _proc
    if _proc and _proc.poll() is None:
        try:
            if sys.platform == "win32":
                # 杀掉整个进程树，确保所有子进程都被终止
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(_proc.pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                _proc.terminate()
                try:
                    _proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _proc.kill()
                    _proc.wait(timeout=5)
        except Exception:
            pass


def kill_port_process(port=8501):
    """杀掉占用指定端口的进程"""
    if sys.platform != "win32":
        return
    try:
        # 查找占用端口的 PID
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", pid],
                    capture_output=True, timeout=10,
                )
                time.sleep(1)
                print(f"[清理] 已结束占用端口 {port} 的旧进程 (PID {pid})")
    except Exception:
        pass


def wait_for_port(host="localhost", port=8501, timeout=30):
    """等待端口就绪"""
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

    # 注册退出清理函数
    atexit.register(_cleanup_proc)
    # 注册信号处理（Ctrl+C）
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    print("=" * 40)
    print("   地址匹配系统 - 正在启动")
    print("=" * 40)
    print(f"项目目录: {os.getcwd()}")
    print()

    # 先杀掉可能残留的旧进程
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
    print(f"   Streamlit PID: {_proc.pid}")

    print("[2/3] 等待服务就绪...")
    if not wait_for_port():
        print()
        print("服务启动超时！以下为 Streamlit 输出：")
        print("-" * 40)
        for _ in range(20):
            line = _proc.stdout.readline()
            if not line:
                break
            print(line, end="")
        print("-" * 40)
        print()
        input("按回车键退出...")
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
