#!/bin/bash
# 双击启动：打开浏览器页面；关闭此终端窗口即退出
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

fail() {
  echo
  echo "❌ $1"
  echo
  echo "按回车键关闭此窗口"
  read -r
  exit 1
}

echo "小语种检查 · 正在启动……"

# 从网上/聊天软件下载的文件带有“隔离”标记，会导致内置程序被 macOS 拦截
xattr -dr com.apple.quarantine "$DIR" 2>/dev/null
chmod +x engine/lang_ocr runtime/python/bin/* 2>/dev/null

ver="$(sw_vers -productVersion)"
[ "${ver%%.*}" -ge 13 ] 2>/dev/null || fail "需要 macOS 13 (Ventura) 或更高版本，当前系统是 $ver"

if ! engine/lang_ocr --serve </dev/null 2>/dev/null | head -1 | grep -q ready; then
  if command -v swiftc >/dev/null 2>&1 && xcode-select -p >/dev/null 2>&1; then
    echo "识别引擎无法直接运行，正在重新编译（约 1 分钟）……"
    swiftc -O engine/lang_ocr.swift -o engine/lang_ocr -module-cache-path "${TMPDIR:-/tmp}/lang_ocr_mc" \
      || fail "识别引擎编译失败"
  else
    fail "识别引擎无法运行。请把此窗口截图发给提供者。"
  fi
fi

PY=""
if [ "$(uname -m)" = "arm64" ] && [ -x runtime/python/bin/python3 ] && runtime/python/bin/python3 -c "" 2>/dev/null; then
  PY="$DIR/runtime/python/bin/python3"
else
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
    [ -x "$c" ] && PY="$c" && break
  done
  if [ -z "$PY" ] && xcode-select -p >/dev/null 2>&1 && [ -x /usr/bin/python3 ]; then
    PY=/usr/bin/python3
  fi
fi
if [ -z "$PY" ]; then
  xcode-select --install 2>/dev/null
  fail "这台 Mac 缺少 Python。已弹出“安装命令行开发者工具”窗口，请点“安装”，装完后重新双击启动。"
fi

"$PY" -s engine/setup_env.py || fail "运行环境准备失败"

echo
"$PY" -s engine/server.py "$@"
