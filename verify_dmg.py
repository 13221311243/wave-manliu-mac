# -*- coding: utf-8 -*-
"""验证 dmg 内 app 是否包含 PyArmor 加密运行时"""
import os
import subprocess
import sys

DMG = "wave漫流-macOS.dmg"
MOUNT = "/Volumes/wave漫流"

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")

print("=== 挂载 dmg ===")
rc, out = run(["hdiutil", "attach", DMG, "-nobrowse", "-readonly"])
print(out[-2000:])
if rc != 0:
    print("挂载失败")
    sys.exit(1)

print("\n=== 查找 .app ===")
apps = []
for root, dirs, files in os.walk(MOUNT):
    for d in dirs:
        if d.endswith(".app"):
            apps.append(os.path.join(root, d))
print("找到 app:", apps)

if not apps:
    print("未找到 .app，列出挂载点内容：")
    rc2, out2 = run(["ls", "-la", MOUNT])
    print(out2)
    run(["hdiutil", "detach", MOUNT])
    sys.exit(2)

app = apps[0]
print("\n=== 检查 PyArmor 运行时 ===")
# PyArmor 8.x 加密产物特征
checks = {
    "pyarmor_runtime_*": False,
    "pyarmor_runtime.pyd/.so": False,
    "protected_data.pyc (混淆后)": False,
}
resources = os.path.join(app, "Contents", "Resources")
if os.path.isdir(resources):
    for f in os.listdir(resources):
        print("  Resources:", f)
        if f.startswith("pyarmor_runtime"):
            checks["pyarmor_runtime_*"] = True
        if "pyarmor_runtime" in f:
            checks["pyarmor_runtime.pyd/.so"] = True

# 检查 PYZ 里的模块（若有 PyArmor，加密模块不会明文出现在 PYZ）
print("\n=== 检查可执行文件 ===")
macos_dir = os.path.join(app, "Contents", "MacOS")
if os.path.isdir(macos_dir):
    for f in os.listdir(macos_dir):
        print("  MacOS:", f)
        exe = os.path.join(macos_dir, f)
        # 搜可执行文件里是否有 pyarmor 字样
        try:
            with open(exe, "rb") as fh:
                data = fh.read(2_000_000)
            if b"pyarmor" in data.lower():
                checks["pyarmor_runtime.pyd/.so"] = True
                print("  ⚠️ 可执行文件内检测到 pyarmor 字符串")
        except Exception as e:
            print("  读取失败:", e)

print("\n=== 结论 ===")
if checks["pyarmor_runtime_*"] or checks["pyarmor_runtime.pyd/.so"]:
    print("✅ 这是 PyArmor 加密版")
else:
    print("❌ 未检测到 PyArmor 加密特征（可能是普通版）")
for k, v in checks.items():
    print(f"  {k}: {'✓' if v else '✗'}")

run(["hdiutil", "detach", MOUNT])
