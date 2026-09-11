"""zipio - zip 安全校验与原子解压工具

职责：
- verify_sha256(data, expected): sha256 校验，返回错误消息或 None
- find_unsafe_names(names): zip 路径穿越检查（/ 开头、.. 穿越），返回非法条目
- atomic_extract_zip(data_bytes, target_dir): 安全地把 zip 解压写入目标目录
    - 使用 tmp 目录 + shutil.move 原子替换流程
    - 兼容三种 zip 结构：apps/<group>/<aid>/ 前缀、<aid>/ 前缀、扁平文件列表

verify_sha256 / find_unsafe_names 同时供 app_operations 的 launcher 自更新复用，
避免"zip 安全检查"在两处各写一遍。
"""
import hashlib
import re
import shutil
import zipfile
from pathlib import Path


def verify_sha256(data_bytes, expected: str) -> str | None:
    """校验 data_bytes 的 sha256；通过返回 None，失败返回错误消息。"""
    actual = hashlib.sha256(data_bytes).hexdigest()
    if actual != expected:
        return f"sha256 校验失败: 期望 {expected[:12]}… 实际 {actual[:12]}…"
    return None


def find_unsafe_names(names) -> list:
    """返回 zip 条目中的非法路径（绝对路径 / .. 穿越）；全部安全返回空列表。"""
    return [n for n in names if n.startswith("/") or ".." in n]


def atomic_extract_zip(data_bytes, target_dir: Path, expected_sha256: str | None = None):
    """原子解压数据包 data_bytes 到 target_dir（target_dir 形如 .../apps/user/<aid>）。

    流程:
    1. sha256 校验（如果传了 expected_sha256）
    2. 写 target_dir.zip.tmp → 开 zip
    3. 非法路径检查（/ 开头、.. 穿越）
    4. 识别 zip 内路径前缀并剥离，只把应用内部文件解压到 tmp.new/
       支持三种 zip 格式：
         A. publish.py 格式：apps/{system|user}/<aid>/file...  → 剥离前缀
         B. 旧格式：<aid>/file...                                → 剥离 <aid>/
         C. 扁平格式：file...                                    → 不剥离
    5. 若旧目录存在 → 直接删除（不保留 .bak）
    6. move(tmp.new → target_dir)
    7. 清理 zip.tmp

    失败时抛出异常，不污染 target_dir。
    返回 (success: bool, msg: str) 形式方便上层使用。
    """
    if expected_sha256:
        err = verify_sha256(data_bytes, expected_sha256)
        if err:
            return False, err

    target_dir = Path(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    aid = target_dir.name

    zip_tmp = target_dir.parent / f"{aid}.zip.tmp"
    tmp_new = target_dir.parent / f"{aid}.tmp.new"

    try:
        zip_tmp.write_bytes(data_bytes)
        with zipfile.ZipFile(zip_tmp) as z:
            all_names = z.namelist()
            if find_unsafe_names(all_names):
                return False, "zip 包含非法路径"
            files = [n for n in all_names if not n.endswith("/")]

            # 识别前缀：格式 A（apps/<dir>/<aid>/）、格式 B（<aid>/）、格式 C（无前缀）
            strip_prefix = ""
            m_a = re.match(r"^(apps/[^/]+/[^/]+/)", files[0]) if files else None
            if m_a and all(n.startswith(m_a.group(1)) for n in files):
                strip_prefix = m_a.group(1)
            elif files and all(n.startswith(aid + "/") for n in files):
                strip_prefix = aid + "/"

            if tmp_new.exists():
                shutil.rmtree(tmp_new, ignore_errors=True)
            tmp_new.mkdir(parents=True, exist_ok=True)

            for n in files:
                rel = n[len(strip_prefix):] if strip_prefix else n
                if not rel or rel.startswith("/"):
                    continue
                # 二次防御：剥离后仍不允许穿越
                if ".." in rel or rel.startswith("/") or Path(rel).is_absolute():
                    continue
                dest = tmp_new / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))

            # 原子替换：直接删除旧目录，move 新目录
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            shutil.move(str(tmp_new), str(target_dir))
        return True, "ok"
    except Exception as e:
        return False, f"解压失败: {e}"
    finally:
        try:
            zip_tmp.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if tmp_new.exists():
                shutil.rmtree(tmp_new, ignore_errors=True)
        except Exception:
            pass