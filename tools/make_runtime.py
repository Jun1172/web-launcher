# -*- coding: utf-8 -*-
"""制作内嵌 Python runtime (Windows x64, Python 3.11 embeddable)。

产出 runtime/win-x64/ 目录:
    python.exe python311.dll python311.zip ... + pip
外加 pip，供 deps_installer 给应用装依赖。

用法:
    python tools/make_runtime.py      # 在仓库根目录下运行（工具箱里点「重建」也可）

布局策略: 删除 embeddable 自带的 python311._pth，回归标准路径行为 ——
PYTHONPATH/站点目录照常生效，launcher 注入的应用依赖目录(<app>/site/)可直接工作。

说明:
    本脚本放在 tools/ 目录，**不放在 runtime/ 内** —— 因为 runtime/ 被
    .gitignore 排除，放在里面会导致"删除 runtime 目录 = 连生成脚本一起删"。
    脚本通过自身位置向上定位仓库根（tools/ 的上一级）。

add 261023: 下载源增加国内镜像回退（python.org/bootstrap.pypa.io 在部分
网络环境不可达，曾导致重建中断留下无 pip 的残缺 runtime）；pip 改为
"下载 wheel 直接解压到 Lib/site-packages"的稳妥方式并增加自检。
"""
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

# 控制台编码加固: GBK 控制台遇到 ✓ 等字符会 UnicodeEncodeError, 统一转 UTF-8 add 261023
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# 本脚本位于 tools/ 目录下，仓库根目录为其上一级
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 产物目录：runtime/win-x64（runtime 本身是二进制产物，不进 git）
OUT = os.path.join(ROOT, 'runtime', 'win-x64')

PY_VER = '3.11.9'
PY_TAG = ''.join(PY_VER.split('.')[:2])  # 3.11.9 -> "311"
# embeddable 包下载源（按序尝试，前两个为国内镜像）
EMBED_URLS = [
    'https://mirrors.huaweicloud.com/python/%s/python-%s-embed-amd64.zip' % (PY_VER, PY_VER),
    'https://registry.npmmirror.com/-/binary/python/%s/python-%s-embed-amd64.zip' % (PY_VER, PY_VER),
    'https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip' % (PY_VER, PY_VER),
]
# pip wheel 下载源（国内镜像优先）
PIP_INDEXES = [
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple',
    'https://pypi.org/simple',
]


def _fetch(url, timeout=60):
    print('    下载 %s' % url)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _download_embed():
    last_err = None
    for url in EMBED_URLS:
        try:
            return _fetch(url)
        except Exception as e:
            print('    ✗ 失败: %s' % e)
            last_err = e
    raise SystemExit('embeddable 包所有下载源均失败: %s' % last_err)


def _install_pip():
    """把 pip 装进 runtime: 优先用当前解释器从镜像源下载 wheel 解压；
    失败则回退 get-pip.py(镜像优先)。"""
    libdir = os.path.join(OUT, 'Lib', 'site-packages')
    os.makedirs(libdir, exist_ok=True)

    # 方式一: pip download pip -> 解压进 site-packages（最稳,不依赖目标解释器联网）
    for idx in PIP_INDEXES:
        tmp = os.path.join(OUT, '_pip_tmp')
        try:
            print('    pip wheel 源: %s' % idx)
            subprocess.run([sys.executable, '-m', 'pip', 'download', 'pip',
                            '--no-deps', '--only-binary', ':all:',
                            '-i', idx, '--dest', tmp],
                           check=True, capture_output=True, timeout=180)
            whl = next(os.path.join(tmp, n) for n in os.listdir(tmp)
                       if n.startswith('pip-') and n.endswith('.whl'))
            zipfile.ZipFile(whl).extractall(libdir)
            shutil.rmtree(tmp, ignore_errors=True)
            return
        except Exception as e:
            print('    ✗ 失败: %s' % e)
            shutil.rmtree(tmp, ignore_errors=True)

    # 方式二: get-pip.py（镜像优先）
    GP_URLS = [
        'https://mirrors.aliyun.com/pypi/get-pip.py',
        'https://bootstrap.pypa.io/get-pip.py',
    ]
    for url in GP_URLS:
        try:
            gp = os.path.join(OUT, 'get-pip.py')
            with open(gp, 'wb') as f:
                f.write(_fetch(url))
            subprocess.run([os.path.join(OUT, 'python.exe'), gp,
                            '--no-warn-script-location', '-i', PIP_INDEXES[0]],
                           check=True, capture_output=True, timeout=300)
            os.remove(gp)
            return
        except Exception as e:
            print('    ✗ 失败: %s' % e)
    raise SystemExit('pip 安装所有方式均失败')


def main():
    if os.path.exists(OUT):
        print('[0/4] 清理已有 runtime ...')
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    print('[1/4] 下载 embeddable 包 (Python %s) ...' % PY_VER)
    zf = zipfile.ZipFile(io.BytesIO(_download_embed()))
    zf.extractall(OUT)

    # 删掉 ._pth: 回归标准路径行为(PYTHONPATH/站点目录照常生效),
    # launcher 注入的应用依赖目录 <app>/site/ 才能被应用看到
    pth = os.path.join(OUT, 'python%s._pth' % PY_TAG)
    if os.path.isfile(pth):
        os.remove(pth)
    libdir = os.path.join(OUT, 'Lib', 'site-packages')
    os.makedirs(libdir, exist_ok=True)

    print('[2/4] 安装 pip ...')
    _install_pip()

    print('[3/4] 验证 ...')
    checks = [
        ('解释器', ['-c', 'import sys; print(sys.version)']),
        ('pip', ['-m', 'pip', '--version']),
        ('基础库', ['-c', 'import sqlite3, ssl, ctypes, socket; print("ok")']),
        ('PYTHONPATH 注入', ['-c', 'import os, sys; '
                               'os.environ["PYTHONPATH"]=r"%s"; '
                               'import site; import importlib; '
                               'sys.path.insert(0, os.environ["PYTHONPATH"]); '
                               'print("ok")' % libdir]),
    ]
    for name, args in checks:
        r = subprocess.run([os.path.join(OUT, 'python.exe')] + args,
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            raise SystemExit('runtime 自检失败: %s' % name)
        print('    ✓ %s: %s' % (name, (r.stdout or '').strip().splitlines()[-1]
                                  if (r.stdout or '').strip() else 'ok'))

    print('[4/4] 清理 ...')
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
    print('提示: 还需要 wheels/ 才能离线安装应用依赖, 运行 python tools/make_wheels.py')


if __name__ == '__main__':
    main()
