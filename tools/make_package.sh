#!/bin/bash
# 生成分享用压缩包 dist/小语种检查.zip（需先有 runtime/python、pylib、models、engine/lang_ocr）
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="$(pwd)"
STAGE_ROOT="$SRC/_build/stage"
STAGE="$STAGE_ROOT/小语种检查"
ZIP="$SRC/dist/小语种检查.zip"

for need in runtime/python/bin/python3 pylib/lingua pylib/PIL models/lid.176.ftz engine/lang_ocr; do
  [ -e "$need" ] || { echo "缺少 $need"; exit 1; }
done
lipo -archs engine/lang_ocr | grep -q x86_64 || echo "提示：engine/lang_ocr 不是通用版本，Intel Mac 需要现场编译"

rm -rf "$STAGE_ROOT"
mkdir -p "$STAGE" "$SRC/dist"
COMMON=(--exclude __pycache__ --exclude .DS_Store --exclude '*.pyc')

rsync -a "${COMMON[@]}" engine ui models 示例图片 启动小语种检查.command 使用说明.txt "$STAGE/"

rsync -a "${COMMON[@]}" --exclude tests --exclude 'numpy*' --exclude 'setuptools*' --exclude 'pybind11*' \
  --exclude _distutils_hack --exclude distutils-precedence.pth --exclude bin pylib "$STAGE/"

rsync -a "${COMMON[@]}" --exclude include --exclude share \
  --exclude 'lib/tcl*' --exclude 'lib/tk*' --exclude 'lib/itcl*' --exclude 'lib/thread*' \
  --exclude 'lib/libtcl*' --exclude 'lib/libtk*' \
  --exclude 'lib/python3.9/test' --exclude 'lib/python3.9/idlelib' --exclude 'lib/python3.9/tkinter' \
  --exclude 'lib/python3.9/turtledemo' --exclude 'lib/python3.9/ensurepip' --exclude 'lib/python3.9/pydoc_data' \
  --exclude 'lib/python3.9/lib-dynload/_tkinter*' \
  runtime "$STAGE/"

chmod +x "$STAGE/启动小语种检查.command" "$STAGE/engine/lang_ocr" "$STAGE"/runtime/python/bin/*
xattr -cr "$STAGE"

rm -f "$ZIP"
(cd "$STAGE_ROOT" && ditto -c -k --norsrc --noextattr --noqtn --keepParent 小语种检查 "$ZIP")
echo "解压后大小：$(du -sh "$STAGE" | cut -f1)"
echo "压缩包：${ZIP}（$(du -h "$ZIP" | cut -f1)）"
