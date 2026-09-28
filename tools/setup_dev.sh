#!/bin/bash
# 从源码准备完整运行环境（与分享包一致）：独立 Python 3.9、pylib 依赖、fastText 模型、通用版识别引擎
# 需要 Apple 芯片 Mac + Xcode 命令行工具（swiftc）
set -euo pipefail
cd "$(dirname "$0")/.."

PBS="https://github.com/astral-sh/python-build-standalone/releases/download/20251014"
PY_TGZ="cpython-3.9.24+20251014-aarch64-apple-darwin-install_only_stripped.tar.gz"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

[ "$(uname -m)" = "arm64" ] || { echo "请在 Apple 芯片的 Mac 上运行"; exit 1; }

if [ ! -x runtime/python/bin/python3 ]; then
  echo "== 下载独立 Python 3.9"
  mkdir -p _build runtime
  curl -fL --retry 3 -o "_build/$PY_TGZ" "$PBS/$PY_TGZ"
  tar xzf "_build/$PY_TGZ" -C runtime
fi
PY=runtime/python/bin/python3

echo "== 安装依赖到 pylib/"
"$PY" -m pip install -q --disable-pip-version-check --upgrade --target pylib -i "$PIP_INDEX" \
  "lingua-language-detector==2.0.2" "fasttext-wheel==0.9.2" regex "pillow==11.3.0" "numpy<2"

if [ ! -f models/lid.176.ftz ]; then
  echo "== 下载 fastText 语言模型"
  mkdir -p models
  curl -fL --retry 3 -o models/lid.176.ftz https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz
fi

echo "== 编译通用版识别引擎（arm64 + x86_64）"
MC="${TMPDIR:-/tmp}/lang_ocr_mc"
mkdir -p _build
swiftc -O -target arm64-apple-macos13.0 engine/lang_ocr.swift -o _build/lang_ocr_arm64 -module-cache-path "$MC"
swiftc -O -target x86_64-apple-macos13.0 engine/lang_ocr.swift -o _build/lang_ocr_x86 -module-cache-path "$MC"
lipo -create _build/lang_ocr_arm64 _build/lang_ocr_x86 -output engine/lang_ocr
codesign -s - -f engine/lang_ocr

echo "完成。双击“启动小语种检查.command”运行，或执行 tools/make_package.sh 生成分享包。"
