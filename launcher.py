"""地址匹配系统一键启动器"""
import subprocess
import webbrowser
import time
import sys
import os
import socket


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
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 40)
    print("   地址匹配系统 - 正在启动")
    print("=" * 40)
    print(f"项目目录: {os.getcwd()}")
    print()

    print("[1/3] 启动 Streamlit 服务...")
    # 启动 Streamlit 子进程
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

    print("[2/3] 等待服务就绪...")
    if not wait_for_port():
        print()
        print("服务启动超时！以下为 Streamlit 输出：")
        print("-" * 40)
        for _ in range(20):
            line = proc.stdout.readline()
            if not line:
                break
            print(line, end="")
        print("-" * 40)
        print()
        input("按回车键退出...")
        proc.kill()
        sys.exit(1)

    print("[3/3] 打开浏览器...")
    webbrowser.open("http://localhost:8501")
    print()
    print("=" * 40)
    print("  浏览器已打开，访问 http://localhost:8501")
    print("  关闭本窗口或按 Ctrl+C 停止服务")
    print("=" * 40)
    print()

    # 持续打印 Streamlit 日志
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
        proc.terminate()
        proc.wait(timeout=5)
        print("服务已停止。")


if __name__ == "__main__":
    main()
