# -*- coding: utf-8 -*-
"""制作内嵌 Python runtime (Windows x64, Python 3.11 embeddable)。

产出 runtime/win-x64/ 目录:
    python.exe python311.dll python311.zip ...
外加 pip (通过 get-pip.py 装入)，供 deps_installer 给应用装依赖。

用法:
    python make_runtime.py

说明:
    本脚本放在仓库根目录，**不放在 runtime/ 内** —— 因为 runtime/ 被
    .gitignore 排除，放在里面会导致"删除 runtime 目录 = 连生成脚本一起删"，
    且 git 无法恢复。
"""
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
# 产物目录：runtime/win-x64（runtime 本身是二进制产物，不进 git）
OUT = os.path.join(HERE, 'runtime', 'win-x64')

PY_VER = '3.11.9'
EMBED_URL = ('https://www.python.org/ftp/python/%s/'
             'python-%s-embed-amd64.zip' % (PY_VER, PY_VER))
GET_PIP_URL = 'https://bootstrap.pypa.io/get-pip.py'


def main():
    if os.path.exists(OUT):
        print('[0/3] 清理已有 runtime ...')
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    print('[1/3] 下载 embeddable 包 (Python %s) ...' % PY_VER)
    with urllib.request.urlopen(EMBED_URL) as r:
        data = r.read()
    zf = zipfile.ZipFile(io.BytesIO(data))
    zf.extractall(OUT)

    # 传统布局: 删掉 ._pth (它会忽略 PYTHONPATH, 使应用级 site/ 失效),
    # 改用标准 python311.zip + Lib\site-packages (site 自动启用)
    # 3.11.9 -> "311"，对应 embeddable 包里的 python311._pth
    py_tag = ''.join(PY_VER.split('.')[:2])
    pth = os.path.join(OUT, 'python%s._pth' % py_tag)
    if os.path.isfile(pth):
        os.remove(pth)
    libdir = os.path.join(OUT, 'Lib', 'site-packages')
    os.makedirs(libdir, exist_ok=True)

    print('[2/3] 安装 pip ...')
    gp = os.path.join(OUT, 'get-pip.py')
    with urllib.request.urlopen(GET_PIP_URL) as r:
        with open(gp, 'wb') as f:
            f.write(r.read())
    subprocess.run([os.path.join(OUT, 'python.exe'), gp, '--no-warn-script-location'],
                   check=True, capture_output=True)
    os.remove(gp)

    print('[3/3] 验证 ...')
    r = subprocess.run([os.path.join(OUT, 'python.exe'), '-c',
                        'import sys, sqlite3, sqlite3.dbapi2, ssl, ctypes, socket; print(sys.version)'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit('runtime 自检失败')
    print(r.stdout.strip())

    # pip 保留在 runtime 里(launcher 的 deps_installer 用它给应用装依赖);
    # 只去掉 setuptools 残留的 pth 引用, 避免每次启动打噪音
    sp = os.path.join(OUT, 'Lib', 'site-packages')
    for name in ('distutils-precedence.pth',):
        p = os.path.join(sp, name)
        if os.path.isfile(p):
            os.remove(p)
    scripts = os.path.join(OUT, 'Scripts')
    if os.path.isdir(scripts):
        shutil.rmtree(scripts, ignore_errors=True)  # 脚本入口不需要, 用 -m pip

    total = 0
    for root, _, files in os.walk(OUT):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    print('完成: %s  (%.1f MB)' % (OUT, total / 1048576.0))
    print()
    print('提示: 还需要 wheels/ 才能离线安装应用依赖, 运行 python make_wheels.py')


if __name__ == '__main__':
    main()
