# publish.py   用法: python publish.py apps/hello
import json, zipfile, hashlib, subprocess, sys
from pathlib import Path

SERVER = "jun@172.18.119.215"      # ← 改成你的用户名和 IP
REMOTE = "/var/www/repo"

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""): h.update(chunk)
    return h.hexdigest()

app_dir = Path(sys.argv[1])
meta = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
zip_name = f"{meta['id']}-{meta['version']}.zip"

print(f"📦 打包 {meta['name']} v{meta['version']}...")
with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as z:
    for f in app_dir.rglob("*"):
        if f.is_file() and ".venv" not in f.parts and f.suffix != ".pyc":
            z.write(f, f.relative_to(app_dir.parent))

print(f"🚀 上传 {zip_name}...")
subprocess.run(["scp", zip_name, f"{SERVER}:{REMOTE}/packages/"], check=True)

print("📋 更新目录...")
# 下载当前目录
index_tmp = Path("_index.json")
subprocess.run(["scp", f"{SERVER}:{REMOTE}/index.json", str(index_tmp)], check=True)
index = json.loads(index_tmp.read_text(encoding="utf-8"))

# 构造新条目
entry = {k: meta[k] for k in
         ("id","name","icon","color","version","changelog","port","cmd","dock")
         if k in meta}
entry["pkg"] = f"packages/{zip_name}"
entry["size"] = Path(zip_name).stat().st_size
entry["sha256"] = sha256(zip_name)

# 更新 apps 列表（替换或追加）
index["apps"] = [a for a in index.get("apps", []) if a["id"] != meta["id"]] + [entry]
import datetime
index["updated"] = datetime.datetime.now().isoformat()

index_tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
subprocess.run(["scp", str(index_tmp), f"{SERVER}:{REMOTE}/index.json"], check=True)

Path(zip_name).unlink()
print(f"✅ 发布完成！客户端刷新商店即可看到 {meta['name']} v{meta['version']}")