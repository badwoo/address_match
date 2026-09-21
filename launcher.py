"""地址匹配系统一键启动器

设计要点：
- 让 Streamlit 继承当前控制台窗口运行，不额外创建窗口。
- 因此关闭 CMD 窗口时，Windows 会一起终止 Streamlit。
- Ctrl+C 会同时发给本程序和 Streamlit，本程序做兜底清理。
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser


_PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit_pid")


def _write_pid(pid):
    try:
        with open(_PID_FILE, "w") as f:
            f.write(str(pid))
    except Exception:
        pass


def _cleanup_pid_file():
    try:
        if os.path.exists(_PID_FILE):
            os.remove(_PID_FILE)
    except Exception:
        pass


def _cleanup_port(port=8501):
    """杀掉占用指定端口的进程（仅 Windows）"""
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
    # 关键：不指定 CREATE_NO_WINDOW，也不 pipe stdout/stderr，
    # 让 Streamlit 直接写当前控制台。关闭控制台时系统会一起终止它。
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true"],
    )
    _write_pid(proc.pid)
    print(f"   Streamlit PID: {proc.pid}")

    print("[2/3] 等待服务就绪...")
    if not wait_for_port():
        print("服务启动超时！")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        _cleanup_pid_file()
        input("按回车键退出...")
        sys.exit(1)

    if proc.poll() is not None:
        print("Streamlit 服务异常退出，请检查上方错误信息。")
        _cleanup_pid_file()
        input("按回车键退出...")
        sys.exit(1)

    print("[3/3] 打开浏览器...")
    try:
        webbrowser.open("http://localhost:8501")
    except Exception as e:
        print(f"   浏览器打开失败: {e}")
        print("   请手动访问 http://localhost:8501")
    print()
    print("=" * 40)
    print("  浏览器已打开，访问 http://localhost:8501")
    print("  关闭本窗口或按 Ctrl+C 停止服务")
    print("=" * 40)
    print()

    try:
        # 主线程阻塞等待 Streamlit；Ctrl+C 会触发 KeyboardInterrupt
        proc.wait()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        _cleanup_pid_file()
        print("服务已停止。")


if __name__ == "__main__":
    main()
