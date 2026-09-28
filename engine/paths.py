"""定位随包依赖目录：pylib/ 是 Apple Silicon + Python 3.9 的预装依赖，其它环境装到 pylib_<标签>/。"""
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUNDLED_TAG = "cp39-arm64"
TAG = "cp%d%d-%s" % (sys.version_info[0], sys.version_info[1], platform.machine())
PYLIB = os.path.join(ROOT, "pylib" if TAG == BUNDLED_TAG else "pylib_" + TAG)

if PYLIB not in sys.path:
    sys.path.insert(0, PYLIB)
