"""启动前自检：依赖能否加载；不能加载（如 Intel Mac / 其它 Python 版本）时自动安装到 pylib_<标签>/。"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths  # noqa: E402

MIRRORS = ["https://pypi.tuna.tsinghua.edu.cn/simple", "https://mirrors.aliyun.com/pypi/simple",
           "https://pypi.org/simple"]
REQUIRED = {"regex": "import regex",
            "lingua-language-detector": "from lingua import Language, LanguageDetectorBuilder; "
                                        "LanguageDetectorBuilder.from_languages(Language.FRENCH, Language.GERMAN).build()"}
OPTIONAL = {"fasttext-wheel": "import fasttext_pybind", "pillow": "from PIL import Image"}
TRIED = os.path.join(paths.PYLIB, ".optional_tried")
MODEL = os.path.join(paths.ROOT, "models", "lid.176.ftz")
MODEL_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"


def ensure_model():
    if os.path.exists(MODEL):
        return
    print("正在下载 fastText 语言模型（约 1MB）……", flush=True)
    os.makedirs(os.path.dirname(MODEL), exist_ok=True)
    try:
        import urllib.request
        with urllib.request.urlopen(MODEL_URL, timeout=60) as r, open(MODEL + ".part", "wb") as f:
            f.write(r.read())
        os.replace(MODEL + ".part", MODEL)
    except Exception as e:  # noqa: BLE001
        print("提示：模型下载失败（%s），将只用 lingua 判断语言。" % e, flush=True)


def works(code):
    code = "import sys; sys.path.insert(0, %r); %s" % (paths.PYLIB, code)
    return subprocess.run([sys.executable, "-s", "-c", code], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def missing(table):
    return [pkg for pkg, code in table.items() if not works(code)]


def pip_install(pkgs):
    for mirror in MIRRORS:
        print("正在下载 %s（%s），首次约 1~3 分钟……" % ("、".join(pkgs), mirror.split("/")[2]), flush=True)
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                            "--prefer-binary", "--upgrade", "--target", paths.PYLIB, "-i", mirror,
                            "--timeout", "30"] + pkgs)
        if r.returncode == 0:
            return True
    return False


def ensure_pip():
    if subprocess.run([sys.executable, "-m", "pip", "--version"], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode != 0:
        subprocess.run([sys.executable, "-m", "ensurepip", "--user"], stdout=subprocess.DEVNULL)


def main():
    ensure_model()
    if works("; ".join(list(REQUIRED.values()) + list(OPTIONAL.values()))):
        return 0
    req = missing(REQUIRED)
    opt = [] if os.path.exists(TRIED) else missing(OPTIONAL)
    if not req and not opt:
        return 0
    print("当前环境（%s）需要补充依赖：%s" % (paths.TAG, "、".join(req + opt)), flush=True)
    ensure_pip()
    if req:
        pip_install(req)
        if missing(REQUIRED):
            print("依赖安装失败：请检查网络后重新双击启动；仍失败请把此窗口截图发给提供者。", flush=True)
            return 1
    for pkg in opt:
        if not pip_install([pkg]) or pkg in missing(OPTIONAL):
            print("提示：%s 安装失败，不影响使用（准确率或标注预览会受影响）。" % pkg, flush=True)
    os.makedirs(paths.PYLIB, exist_ok=True)
    open(TRIED, "w").close()
    print("依赖准备完成。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
