"""WebLauncher 薄壳入口
真正的实现在 launcher/ 包中。直接运行:
    python launcher.py
或  python -m launcher
"""
import sys
from pathlib import Path

# 确保项目根在 sys.path 中，以便 import launcher 包
BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from launcher.__main__ import main

if __name__ == "__main__":
    main()
