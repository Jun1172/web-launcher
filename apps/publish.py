import json, zipfile, hashlib, subprocess, sys
from pathlib import Path

BASE = Path(__file__).parent.parent
CONFIG_JSON = BASE / "config.json"

def load_config():
    if CONFIG_JSON.exists():
        return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    return {}

CONFIG = load_config()
PUBLISH_CFG = CONFIG.get("publish", {})
SERVER = PUBLISH_CFG.get("server", "jun@172.18.119.215")
REMOTE = PUBLISH_CFG.get("remote_path", "/var/www/repo")
PACKAGES_DIR = PUBLISH_CFG.get("packages_dir", "packages")

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

if len(sys.argv) < 2:
    print("用法: python publish.py <app_dir>")
    print("示例: python publish.py apps/hello")
    sys.exit(1)

app_dir = Path(sys.argv[1])
if not app_dir.is_absolute():
    app_dir = (BASE / app_dir).resolve()

app_json = app_dir / "app.json"
if not app_json.exists():
    print(f"错误: {app_json} 不存在，应用必须包含 app.json")
    sys.exit(1)

meta = json.loads(app_json.read_text(encoding="utf-8"))
zip_name = f"{meta['id']}-{meta['version']}.zip"

print(f"📦 打包 {meta['name']} v{meta['version']} (id={meta['id']})...")
with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as z:
    for f in app_dir.rglob("*"):
        if f.is_file() and ".venv" not in f.parts and f.suffix != ".pyc" and f.name != "__pycache__":
            arcname = f.relative_to(app_dir.parent)
            z.write(f, arcname)

print(f"🚀 上传 {zip_name} → {SERVER}:{REMOTE}/{PACKAGES_DIR}/")
subprocess.run(["scp", zip_name, f"{SERVER}:{REMOTE}/{PACKAGES_DIR}/"], check=True)

print("📋 更新目录...")
index_tmp = BASE / "_index.json"
subprocess.run(["scp", f"{SERVER}:{REMOTE}/index.json", str(index_tmp)], check=True)
index = json.loads(index_tmp.read_text(encoding="utf-8"))

entry = {k: meta[k] for k in
         ("id", "name", "icon", "color", "version", "changelog", "port", "cmd", "dock", "system")
         if k in meta}
entry["pkg"] = f"{PACKAGES_DIR}/{zip_name}"
entry["size"] = Path(zip_name).stat().st_size
entry["sha256"] = sha256(zip_name)

index["apps"] = [a for a in index.get("apps", []) if a["id"] != meta["id"]] + [entry]
import datetime
index["updated"] = datetime.datetime.now().isoformat()

index_tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
subprocess.run(["scp", str(index_tmp), f"{SERVER}:{REMOTE}/index.json"], check=True)

Path(zip_name).unlink()
print(f"✅ 发布完成！客户端刷新商店即可看到 {meta['name']} v{meta['version']}")