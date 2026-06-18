"""地址匹配系统一键启动器"""
import subprocess
import webbrowser
import time
import sys
import os
import socket


_PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit_pid")


def _write_pid(pid):
    try:
        with open(_PID_FILE, "w") as f:
            f.write(str(pid))
    except Exception:
        pass


def _cleanup_port(port=8501):
    """杀掉占用指定端口的进程（纯 taskkill，无 ctypes 依赖）"""
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
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
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)

    print("=" * 40)
    print("   地址匹配系统 - 正在启动")
    print("=" * 40)
    print(f"项目目录: {project_dir}")
    print()

    # 启动前清理残留
    print("[0/3] 清理残留进程...")
    _cleanup_port(8501)

    print("[1/3] 启动 Streamlit 服务...")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **kwargs,
    )
    _write_pid(proc.pid)
    print(f"   Streamlit PID: {proc.pid}")

    print("[2/3] 等待服务就绪...")
    if not wait_for_port():
        print("服务启动超时！")
        proc.kill()
        proc.wait()
        input("按回车键退出...")
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
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            if line:
                print(line, end="")
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        # 关闭 Streamlit
        try:
            if proc.poll() is None:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10,
                )
                proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        # 清理 PID 文件
        try:
            os.remove(_PID_FILE)
        except Exception:
            pass
        print("服务已停止。")


if __name__ == "__main__":
    main()
