"""
打包脚本 — 将导航系统打包为可执行文件
用法：python build_exe.py
输出：dist/NavigationSystem.exe (Windows) / dist/NavigationSystem (Linux/Mac)
"""
import subprocess, sys, os

def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--windowed",
        "--name=NavigationSystem",
        "--add-data", f"navigation{os.pathsep}navigation",
        "main_gui.py",
    ]
    if os.path.exists("icon.ico"):
        cmd += ["--icon", "icon.ico"]
    print("打包命令:", " ".join(cmd))
    r = subprocess.run(cmd, check=False)
    if r.returncode == 0:
        out = os.path.join("dist", "NavigationSystem" + (".exe" if sys.platform=="win32" else ""))
        print(f"\n✅ 打包成功！\n可执行文件：{os.path.abspath(out)}")
    else:
        print("\n❌ 打包失败，请检查上方错误信息")
        sys.exit(1)

if __name__ == "__main__":
    build()
