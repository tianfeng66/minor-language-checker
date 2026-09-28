"""小语种检查 - 本地服务：托管网页界面，调用 Vision 识别与语言判定，导出到小语种文件夹。"""
import json
import os
import queue
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UI_DIR = os.path.join(ROOT, "ui")
sys.path.insert(0, HERE)

from decide import analyze  # noqa: E402

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".gif", ".tif", ".tiff"}
TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".srt", ".vtt", ".ass", ".html", ".htm", ".xml", ".log"}
DOC_EXT = {".pdf", ".docx"}
ARCHIVE_EXT = {".zip"}
SUPPORTED = IMAGE_EXT | TEXT_EXT | DOC_EXT
LEVEL_GRIDS = {0: [], 1: [2], 2: [2, 3], 3: [2, 3, 5]}
WORKERS = max(2, min(4, (os.cpu_count() or 4) // 2))
SESSION_DIR = tempfile.mkdtemp(prefix="xiaoyuzhong_")
ITEMS = {}
ITEMS_LOCK = threading.Lock()


class Engine:
    """常驻的 lang_ocr --serve 进程。"""

    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.start()

    def start(self):
        self.proc = subprocess.Popen([os.path.join(HERE, "lang_ocr"), "--serve"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("lang_ocr 无法运行")
        self.info = json.loads(line)

    def run(self, path, full=True, grids=None, max_pages=20, timeout=180):
        req = {"id": "x", "path": path, "full": full, "grids": grids or [], "maxPages": max_pages}
        with self.lock:
            try:
                self.proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
                ready, _, _ = select.select([self.proc.stdout], [], [], timeout)
                if not ready:
                    self.proc.kill()
                    self.start()
                    return {"error": "读取超时", "timeout": True}
                line = self.proc.stdout.readline()
                if line:
                    return json.loads(line)
            except (BrokenPipeError, OSError, ValueError):
                pass
            self.start()
        return {"error": "识别引擎崩溃（可能是文件损坏）", "crash": True}


POOL = queue.Queue()


def init_pool():
    for _ in range(WORKERS):
        POOL.put(Engine())


def ocr(path, full=True, grids=None):
    eng = POOL.get()
    try:
        return eng.run(path, full, grids)
    finally:
        POOL.put(eng)


def flat_items(res):
    out = []
    for pg in res.get("pages", []):
        for it in pg["items"]:
            it = dict(it)
            it["page"] = pg.get("page", "")
            out.append(it)
    return out


def analyze_image(path, level, sens, early_stop=True):
    t0 = time.time()
    res = ocr(path, full=True, grids=[])
    if "error" in res:
        if res.get("timeout"):
            return skipped("读取超时（文件过大或损坏）")
        if res.get("crash") or res.get("incomplete"):
            return skipped(res["error"])
        return skipped("图片无法读取（文件损坏或格式不支持）")
    if not res.get("pages"):
        return skipped("文件中没有可读取的页面")
    items = flat_items(res)
    pages = [{"page": p.get("page", ""), "width": p["width"], "height": p["height"]} for p in res.get("pages", [])]
    verdict = analyze(items, sensitivity=sens)
    passes = ["全图"]
    for g in LEVEL_GRIDS.get(level, [2]):
        if early_stop and verdict["level"] == "确定":
            break
        more = ocr(path, full=False, grids=[g])
        items = merge_items(items, flat_items(more))
        verdict = analyze(items, sensitivity=sens)
        passes.append("%dx%d" % (g, g))
    verdict.update({"items": items, "pages": pages, "passes": passes, "ms": int((time.time() - t0) * 1000)})
    return verdict


def merge_items(base, extra):
    def key(it):
        return "".join(ch for ch in it["text"].lower() if ch.isalnum())
    out = list(base)
    for e in extra:
        eb, ek = e["box"], key(e)
        dup = False
        for b in out:
            bb = b["box"]
            ix = max(0, min(eb[0] + eb[2], bb[0] + bb[2]) - max(eb[0], bb[0]))
            iy = max(0, min(eb[1] + eb[3], bb[1] + bb[3]) - max(eb[1], bb[1]))
            inter = ix * iy
            small = min(eb[2] * eb[3], bb[2] * bb[3]) or 1e-9
            if b.get("page") == e.get("page") and inter / small > 0.6 and (ek in key(b) or key(b) in ek):
                if len(ek) > len(key(b)) and e["conf"] >= b["conf"]:
                    b.update(e)
                dup = True
                break
        if not dup:
            out.append(e)
    return out


def read_text_file(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "gb18030", "latin-1"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def docx_text(path):
    import re
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def analyze_textlike(text, sens):
    import html
    import re
    text = html.unescape(re.sub(r"<[^>]+>", " ", text)) if "<" in text else text
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:5000]
    items = [{"text": ln[:400], "conf": 1.0} for ln in lines]
    v = analyze(items, exact=True, sensitivity=sens)
    v.update({"items": items[:300], "pages": [], "passes": ["文本"], "ms": 0})
    return v


def truncated(path, ext):
    """JPEG 应以 FFD9 结尾、PNG 应含 IEND 块；缺失说明文件被截断。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(8)
            f.seek(max(0, size - (1 << 20)))
            tail = f.read()
    except OSError:
        return False
    if ext in (".jpg", ".jpeg") and head[:2] == b"\xff\xd8":
        return b"\xff\xd9" not in tail
    if ext == ".png" and head[:8] == b"\x89PNG\r\n\x1a\n":
        return b"IEND" not in tail
    return False


def skipped(reason):
    return {"skipped": True, "reason": reason, "verdict": "无法读取", "level": "", "langs": [],
            "note": "无法读取，已跳过：" + reason, "marks": [], "items": [], "pages": [], "passes": []}


def analyze_file(path, level, sens, early_stop=True):
    ext = os.path.splitext(path)[1].lower()
    if not os.path.exists(path):
        return skipped("文件不存在或已被移走")
    if os.path.getsize(path) == 0:
        return skipped("空文件（0 字节）")
    if truncated(path, ext):
        return skipped("图片不完整（文件结尾缺失，可能下载/拷贝时被截断）")
    try:
        if ext in IMAGE_EXT or ext == ".pdf":
            return analyze_image(path, level, sens, early_stop)
        if ext == ".docx":
            return analyze_textlike(docx_text(path), sens)
        if ext in TEXT_EXT:
            return analyze_textlike(read_text_file(path), sens)
    except Exception as e:  # noqa: BLE001
        return skipped("文件无法读取（%s）" % e)
    return skipped("不支持的文件类型")


def register(path, name, source, rel=None):
    iid = uuid.uuid4().hex[:12]
    with ITEMS_LOCK:
        ITEMS[iid] = {"path": path, "name": name, "source": source, "rel": rel or name}
    return iid


def expand_upload(path, name):
    """上传的文件：zip 解压出支持的文件，其余原样登记。返回 [(id, name, rel)]。"""
    ext = os.path.splitext(name)[1].lower()
    if ext not in ARCHIVE_EXT:
        return [(register(path, name, "upload"), name, name)]
    out = []
    dest = os.path.join(SESSION_DIR, uuid.uuid4().hex[:8])
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            raw = info.filename
            if not (info.flag_bits & 0x800):
                try:
                    raw = raw.encode("cp437").decode("gbk")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            if info.is_dir() or "__MACOSX" in raw or os.path.basename(raw).startswith("."):
                continue
            if os.path.splitext(raw)[1].lower() not in SUPPORTED:
                continue
            target = os.path.join(dest, raw)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            rel = os.path.join(os.path.splitext(name)[0], raw)
            out.append((register(target, os.path.basename(raw), "upload", rel), os.path.basename(raw), rel))
    return out


def list_folder(root):
    root = os.path.expanduser(root.strip().strip("'\"").replace("\\ ", " "))
    if not os.path.exists(root):
        raise ValueError("路径不存在：%s" % root)
    if os.path.isfile(root):
        return [(root, os.path.basename(root))]
    files = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".") and d not in ("小语种", "__MACOSX")]
        for fn in sorted(fns):
            if fn.startswith("."):
                continue
            if os.path.splitext(fn)[1].lower() in SUPPORTED:
                full = os.path.join(dp, fn)
                files.append((full, os.path.relpath(full, root)))
    return files


def unique_path(p):
    if not os.path.exists(p):
        return p
    base, ext = os.path.splitext(p)
    i = 2
    while os.path.exists("%s(%d)%s" % (base, i, ext)):
        i += 1
    return "%s(%d)%s" % (base, i, ext)


def set_finder_comment(path, text):
    import plistlib
    try:
        data = plistlib.dumps(text, fmt=plistlib.FMT_BINARY).hex()
        subprocess.run(["xattr", "-wx", "com.apple.metadata:kMDItemFinderComment", data, path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def annotate(src, dst, marks):
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError:
        return False
    try:
        try:
            im = Image.open(src)
            im.load()
        except Exception:  # noqa: BLE001
            tmp = os.path.join(SESSION_DIR, "an_" + uuid.uuid4().hex + ".jpg")
            subprocess.run(["sips", "-s", "format", "jpeg", src, "--out", tmp],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            im = Image.open(tmp)
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((2400, 2400))
        d = ImageDraw.Draw(im)
        W, H = im.size
        lw = max(4, W // 250)
        for m in marks:
            b = m.get("box")
            if not b or m.get("page"):
                continue
            color = (230, 30, 30) if m.get("level") == "strong" else (255, 150, 0)
            d.rectangle([b[0] * W - lw, b[1] * H - lw, (b[0] + b[2]) * W + lw, (b[1] + b[3]) * H + lw],
                        outline=color, width=lw)
        im.save(dst, "JPEG", quality=85)
        return True
    except Exception:  # noqa: BLE001
        return False


def do_export(req):
    import csv
    out_dir = os.path.expanduser(req.get("outDir") or "~/Desktop/小语种检查结果")
    mode = req.get("mode", "copy")
    split = req.get("splitSuspect", True)
    rename = req.get("rename", True)
    want_annot = req.get("annotate", True)
    include_others = req.get("includeOthers", False)
    minor_dir = os.path.join(out_dir, "小语种")
    os.makedirs(minor_dir, exist_ok=True)
    rows, done, errors, unreadable = [], 0, [], []
    for it in req.get("items", []):
        reg = ITEMS.get(it.get("id"))
        if not reg or not os.path.exists(reg["path"]):
            errors.append("%s：源文件不存在" % it.get("name"))
            continue
        verdict, level = it.get("verdict"), it.get("level", "")
        if verdict == "无法读取":
            rows.append(row_of(it, reg, "", "无法读取，已跳过"))
            unreadable.append("%s\t%s" % (reg["rel"] if reg["source"] == "upload" else reg["path"], it.get("reason", "")))
            continue
        langs = it.get("langNames") or []
        if verdict == "小语种":
            folder = os.path.join(minor_dir, "疑似待复核") if (split and level == "疑似") else minor_dir
            tag = ("疑似-" if level == "疑似" else "") + ("-".join(langs[:3]) or "小语种")
        elif include_others:
            folder, tag = os.path.join(out_dir, "非小语种"), ""
        else:
            rows.append(row_of(it, reg, "", "未导出"))
            continue
        os.makedirs(folder, exist_ok=True)
        name = reg["name"]
        if rename and tag:
            name = "【%s】%s" % (tag, name)
        dst = unique_path(os.path.join(folder, name))
        try:
            if mode == "move" and reg["source"] == "path":
                shutil.move(reg["path"], dst)
                reg["path"] = dst
            else:
                shutil.copy2(reg["path"], dst)
            note = it.get("note", "")
            if it.get("manual"):
                note = "[人工判定] " + note
            set_finder_comment(dst, note)
            if want_annot and verdict == "小语种" and it.get("marks"):
                adir = os.path.join(minor_dir, "标注预览")
                os.makedirs(adir, exist_ok=True)
                annotate(dst, unique_path(os.path.join(adir, os.path.splitext(name)[0] + ".jpg")), it["marks"])
            rows.append(row_of(it, reg, dst, "已移动" if mode == "move" and reg["source"] == "path" else "已复制"))
            done += 1
        except Exception as e:  # noqa: BLE001
            errors.append("%s：%s" % (reg["name"], e))
    header = ["文件名", "原始位置", "判定", "置信", "语种", "备注", "人工修改", "导出位置", "状态"]
    minor_rows = [r for r in rows if r[2] == "小语种"]
    for path, data in ((os.path.join(minor_dir, "备注.csv"), minor_rows), (os.path.join(out_dir, "检查报告.csv"), rows)):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(data)
    if unreadable:
        with open(os.path.join(out_dir, "无法读取的文件.txt"), "w", encoding="utf-8") as f:
            f.write("以下 %d 个文件无法读取，已跳过（文件\t原因）：\n" % len(unreadable) + "\n".join(unreadable) + "\n")
    return {"ok": True, "outDir": out_dir, "exported": done, "errors": errors, "minor": len(minor_rows),
            "unreadable": len(unreadable)}


def row_of(it, reg, dst, status):
    return [reg["name"], reg["rel"] if reg["source"] == "upload" else reg["path"], it.get("verdict", ""),
            it.get("level", ""), "、".join(it.get("langNames") or []), it.get("note", ""),
            "是" if it.get("manual") else "", dst, status]


BROWSER_OK = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp", ".svg": "image/svg+xml"}
READY = threading.Event()


def preview_path(reg):
    ext = os.path.splitext(reg["path"])[1].lower()
    if ext in BROWSER_OK:
        return reg["path"]
    if ext in IMAGE_EXT or ext == ".pdf":
        out = os.path.join(SESSION_DIR, "pv_" + uuid.uuid5(uuid.NAMESPACE_URL, reg["path"]).hex + ".jpg")
        if not os.path.exists(out):
            subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "2000", reg["path"], "--out", out],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        return out if os.path.exists(out) else None
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/health":
            return self.send_json({"ready": READY.is_set(), "workers": WORKERS, "error": WARMUP["error"],
                                   "warnings": WARMUP["warnings"]})
        if u.path == "/api/preview":
            reg = ITEMS.get(q.get("id", [""])[0])
            p = preview_path(reg) if reg else None
            return self.send_file(p) if p else self.send_json({"error": "无预览"}, 404)
        name = "index.html" if u.path in ("/", "") else unquote(u.path.lstrip("/"))
        p = os.path.normpath(os.path.join(UI_DIR, name))
        if p.startswith(UI_DIR) and os.path.isfile(p):
            return self.send_file(p)
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/upload":
                name = os.path.basename(q.get("name", ["file"])[0])
                rel = q.get("rel", [name])[0]
                n = int(self.headers.get("Content-Length") or 0)
                d = os.path.join(SESSION_DIR, uuid.uuid4().hex[:8])
                os.makedirs(d)
                path = os.path.join(d, name)
                with open(path, "wb") as f:
                    left = n
                    while left > 0:
                        chunk = self.rfile.read(min(left, 1 << 20))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                files = expand_upload(path, name)
                if rel != name and len(files) == 1:
                    ITEMS[files[0][0]]["rel"] = rel
                    files = [(files[0][0], files[0][1], rel)]
                return self.send_json({"files": [{"id": i, "name": nm, "rel": r} for i, nm, r in files]})
            req = self.body_json()
            if u.path == "/api/list":
                files = list_folder(req.get("path", ""))
                out = [{"id": register(p, os.path.basename(p), "path", rel), "name": os.path.basename(p), "rel": rel}
                       for p, rel in files]
                return self.send_json({"files": out})
            if u.path == "/api/analyze":
                while not READY.wait(1):
                    if WARMUP["error"]:
                        return self.send_json({"error": WARMUP["error"]})
                reg = ITEMS.get(req.get("id"))
                if not reg:
                    return self.send_json(skipped("文件已失效，请重新添加"))
                res = analyze_file(reg["path"], int(req.get("level", 1)), req.get("sens", "normal"),
                                   req.get("earlyStop", True))
                return self.send_json(res)
            if u.path == "/api/export":
                return self.send_json(do_export(req))
            if u.path == "/api/reveal":
                p = os.path.expanduser(req.get("path", ""))
                if os.path.exists(p):
                    subprocess.run(["open", p])
                return self.send_json({"ok": True})
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": str(e)}, 500)
        self.send_json({"error": "not found"}, 404)


WARMUP = {"error": None, "warnings": []}


def warmup():
    try:
        init_pool()
    except Exception as e:  # noqa: BLE001
        WARMUP["error"] = "识别引擎启动失败（需要 macOS 13 或更高版本）：%s" % e
        print(WARMUP["error"], flush=True)
        return
    try:
        from classifier import get_lid
        WARMUP["warnings"] = get_lid().warnings
    except Exception as e:  # noqa: BLE001
        WARMUP["error"] = "语言模型加载失败：%s" % e
        print(WARMUP["error"], flush=True)
        return
    READY.set()


def main():
    port = int(os.environ.get("PORT", "8765"))
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    else:
        sys.exit("没有可用端口")
    threading.Thread(target=warmup, daemon=True).start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    print("小语种检查已启动：%s （关闭此窗口即退出）" % url, flush=True)
    if "--no-browser" not in sys.argv:
        subprocess.Popen(["open", url])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutil.rmtree(SESSION_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
