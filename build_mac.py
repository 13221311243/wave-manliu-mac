# -*- coding: utf-8 -*-
"""wave漫流 macOS 打包脚本（GitHub Actions macos runner 上执行）

流程：
1. 从 app.ico 生成 app.icns（Pillow 渲染多尺寸 PNG + iconutil）
2. PyArmor 加密核心模块（ui/core/skills/edit_studio）→ --pack 接管 PyInstaller 打包 .app
3. 校验 .app 结构（可执行文件存在、Info.plist 名字正确）
4. hdiutil 制作 .dmg
"""
import os
import shlex
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


def _plain_pyinstaller(icns):
    """普通 PyInstaller 打包（PyArmor 不可用/失败时的回退）"""
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
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def build_app(icns):
    """PyArmor 加密核心模块（ui/core/skills/edit_studio）后由 PyArmor --pack 接管 PyInstaller 打包。

    PyArmor 9.x 的 --pack 只接受 spec 文件 / onefile / onedir（不再接受命令字符串），
    所以先 pyi-makespec 生成 spec，再 pyarmor gen --pack <spec>。
    加密范围 = 含 SYSTEM_PROMPT 的 ui.app_ui + 激活校验 license_guard + 全部业务模块。
    入口 main.py 不加密（启动器）；PyArmor 自动注入运行时并收集加密模块。
    若 PyArmor 失败则回退普通 PyInstaller 打包（保证出包）。
    """
    print("[2/4] PyArmor 加密核心模块 + PyInstaller 打包 .app ...")
    pyarmor_ok = False

    # 1. 生成 PyInstaller spec（仅生成 spec，不打壳）
    spec_file = os.path.join(ROOT, APP_NAME + ".spec")
    makespec = shutil.which("pyi-makespec") or [
        sys.executable, "-m", "PyInstaller.utils.makespec"]
    if isinstance(makespec, str):
        makespec_cmd = [makespec]
    else:
        makespec_cmd = list(makespec)
    makespec_cmd += ["--windowed", "--name", APP_NAME]
    if icns:
        makespec_cmd += ["--icon", icns]
    makespec_cmd += ["--add-data", "bg.jpg:.", os.path.join(ROOT, "main.py")]
    r = subprocess.run(makespec_cmd, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(spec_file):
        print("⚠️ spec 生成失败，回退普通 PyInstaller 打包：")
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        r = _plain_pyinstaller(icns)
        if r.returncode != 0:
            print(r.stdout[-4000:])
            print(r.stderr[-4000:])
            raise SystemExit("PyInstaller 打包失败")
    else:
        # 2. PyArmor 加密核心模块并用 spec 打包（PyArmor 9 必须用 console script）
        pyarmor_bin = shutil.which("pyarmor")
        if not pyarmor_bin:
            for cand in [os.path.join(os.path.dirname(sys.executable), "pyarmor")]:
                if os.path.exists(cand):
                    pyarmor_bin = cand
                    break
        if not pyarmor_bin:
            print("⚠️ 未找到 pyarmor 可执行文件，回退普通 PyInstaller 打包")
            r = _plain_pyinstaller(icns)
            if r.returncode != 0:
                print(r.stdout[-4000:])
                print(r.stderr[-4000:])
                raise SystemExit("PyInstaller 打包失败")
        else:
            protected = [
                # 入口必须加密：PyArmor --pack spec 模式要求 spec 入口脚本也在加密列表中
                "main.py",
                # 敏感常量：SYSTEM_PROMPT 提示词体系 + 题材导演手法库（核心竞争力）
                "skills/protected_data.py",
                "skills/protected_genres_a.py",
                "skills/protected_genres_b.py",
                # 激活校验 + 核心业务逻辑
                "skills/license_guard.py",
                "skills/base_skill.py",
                "skills/llm_skill.py",
                "skills/image_skill.py",
                "skills/video_skill.py",
                "skills/doc_reader.py",
                "core/agent.py",
            ]
            # 注意：不能 -r 递归（ui/app_ui.py 542KB 和 edit_studio.py 66KB
            # 超 PyArmor 免费版 ~60KB marshal 单文件限制，会 out of license）
            pyarmor_cmd = [
                pyarmor_bin, "gen",
                "--pack", spec_file,
                "-O", os.path.join(BUILD, "pyarmor"),
            ] + protected
            r = subprocess.run(pyarmor_cmd, cwd=ROOT, capture_output=True, text=True)
            if r.returncode != 0:
                print("⚠️ PyArmor 加密/打包失败，回退普通 PyInstaller 打包：")
                print(r.stdout[-3000:])
                print(r.stderr[-3000:])
                r = _plain_pyinstaller(icns)
                if r.returncode != 0:
                    print(r.stdout[-4000:])
                    print(r.stderr[-4000:])
                    raise SystemExit("PyInstaller 打包失败")
            else:
                pyarmor_ok = True

    app_dir = os.path.join(DIST, APP_NAME + ".app")
    if not os.path.isdir(app_dir):
        # PyArmor --pack 会把产物放到 build/pyarmor 下（distpath 被 PyArmor 接管）
        app_dir = os.path.join(BUILD, "pyarmor", APP_NAME + ".app")
    exe = os.path.join(app_dir, "Contents", "MacOS", APP_NAME)
    if not os.path.isfile(exe):
        # 中文名可执行文件有时为 wave漫流
        entries = os.listdir(os.path.join(app_dir, "Contents", "MacOS"))
        raise SystemExit("可执行文件缺失, MacOS 目录: %s" % entries)
    print("[2/4] .app 打包完成（PyArmor 加密: %s）: %s" % ("✅" if pyarmor_ok else "❌未加密-回退版", app_dir))
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
