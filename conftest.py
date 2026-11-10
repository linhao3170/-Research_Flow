"""pytest 根配置：确保仓库根目录可导入 researchflow 包。"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))