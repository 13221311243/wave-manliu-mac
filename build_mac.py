# -*- coding: utf-8 -*-
"""wave漫流 macOS 打包脚本（GitHub Actions macos runner 上执行）

流程：
1. 从 app.ico 生成 app.icns（Pillow 渲染多尺寸 PNG + iconutil）
2. PyInstaller 打包 .app（--windowed，含 tkinter/bg.jpg）
3. 校验 .app 结构（可执行文件存在、Info.plist 名字正确）
4. hdiutil 制作 .dmg
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "wave漫流"
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")


def build_icns():
    """app.ico -> iconset -> app.icns"""
    icns = os.path.join(ROOT, "app.icns")
    if os.path.exists(icns):
        print("[1/4] app.icns 已存在，跳过生成")
        return icns
    from PIL import Image
    ico = Image.open(os.path.join(ROOT, "app.ico"))
    # 取最大尺寸帧
    ico = ico.convert("RGBA")
    iconset = os.path.join(BUILD, "AppIcon.iconset")
    os.makedirs(iconset, exist_ok=True)
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    for s in sizes:
        img = ico.resize((s, s), Image.LANCZOS)
        name = "icon_%dx%d.png" % (s, s)
        img.save(os.path.join(iconset, name))
        if s >= 32:
            img.save(os.path.join(iconset, "icon_%dx%d@2x.png" % (s // 2, s // 2)))
    r = subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("iconutil 失败:", r.stderr)
        # 兜底：无图标也能打包
        return None
    print("[1/4] app.icns 生成完成")
    return icns


def build_app(icns):
    print("[2/4] PyInstaller 打包 .app ...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--windowed",
        "--name", APP_NAME,
        "--distpath", DIST,
        "--workpath", BUILD,
    ]
    if icns:
        cmd += ["--icon", icns]
    cmd += ["--add-data", "bg.jpg:.",
            os.path.join(ROOT, "main.py")]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-4000:])
        print(r.stderr[-4000:])
        raise SystemExit("PyInstaller 打包失败")
    app_dir = os.path.join(DIST, APP_NAME + ".app")
    exe = os.path.join(app_dir, "Contents", "MacOS", APP_NAME)
    if not os.path.isfile(exe):
        # 中文名可执行文件有时为 wave漫流
        entries = os.listdir(os.path.join(app_dir, "Contents", "MacOS"))
        raise SystemExit("可执行文件缺失, MacOS 目录: %s" % entries)
    print("[2/4] .app 打包完成:", app_dir)
    return app_dir


def build_dmg(app_dir):
    print("[3/4] 制作 .dmg ...")
    os.makedirs(DIST, exist_ok=True)
    dmg = os.path.join(DIST, APP_NAME + "-macOS.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    # 先做 rw 镜像，再压缩为最终 dmg
    rw = os.path.join(BUILD, "wave.dmg")
    if os.path.exists(rw):
        os.remove(rw)
    r1 = subprocess.run(
        ["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", app_dir,
         "-ov", "-format", "UDZO", "-fs", "HFS+", dmg],
        capture_output=True, text=True)
    if r1.returncode != 0:
        print(r1.stderr)
        raise SystemExit("hdiutil 制作 dmg 失败")
    print("[3/4] dmg 完成:", dmg)
    return dmg


def main():
    print("=== wave漫流 macOS 打包 ===")
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(DIST, exist_ok=True)
    icns = build_icns()
    app_dir = build_app(icns)
    dmg = build_dmg(app_dir)
    print("\n[4/4] ✅ 产物:", dmg, "(%d MB)" % (os.path.getsize(dmg) // 1048576))


if __name__ == "__main__":
    main()
