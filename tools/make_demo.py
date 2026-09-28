"""生成随包分享的示例文件（示例图片/），用法：runtime/python/bin/python3 -s tools/make_demo.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import paths  # noqa: E402,F401
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT = os.path.join(ROOT, "示例图片")
F = "/System/Library/Fonts/"
FS = F + "Supplemental/"
FONTS = {
    "latin": FS + "Arial Bold.ttf",
    "latin_r": FS + "Arial.ttf",
    "serif": FS + "Georgia Bold.ttf",
    "cjk": F + "Hiragino Sans GB.ttc",
    "ja": F + "ヒラギノ角ゴシック W6.ttc",
    "ko": F + "AppleSDGothicNeo.ttc",
    "uni": FS + "Arial Unicode.ttf",
}


def font(key, size):
    return ImageFont.truetype(FONTS[key], size)


def gradient(w, h, c1, c2):
    im = Image.new("RGB", (w, h), c1)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    return im


def center(d, y, text, f, fill, w):
    x0, _, x1, _ = d.textbbox((0, 0), text, font=f)
    d.text(((w - (x1 - x0)) / 2, y), text, font=f, fill=fill)


def card(name, size, bg, lines):
    w, h = size
    im = gradient(w, h, *bg)
    d = ImageDraw.Draw(im)
    for y, text, key, fs, color in lines:
        center(d, y, text, font(key, fs), color, w)
    path = os.path.join(OUT, name)
    im.save(path, quality=90)
    return im, d


def main():
    os.makedirs(OUT, exist_ok=True)
    card("01_法语招牌.jpg", (1600, 900), ((60, 40, 30), (25, 18, 12)), [
        (170, "BOULANGERIE", "serif", 150, (240, 205, 140)),
        (360, "PÂTISSERIE · CAFÉ", "latin", 80, (250, 250, 240)),
        (560, "Ouvert du lundi au samedi", "latin_r", 60, (220, 220, 210)),
        (700, "法式面包店", "cjk", 56, (240, 205, 140)),
    ])
    card("02_德语提示牌.png", (1400, 900), ((20, 110, 60), (10, 80, 40)), [
        (180, "NOTAUSGANG", "latin", 150, (255, 255, 255)),
        (420, "Bitte nicht rauchen", "latin", 90, (255, 255, 255)),
        (600, "Eingang für Besucher", "latin_r", 70, (220, 240, 225)),
    ])
    card("03_俄语海报.png", (1400, 1000), ((150, 20, 30), (80, 10, 20)), [
        (200, "Добро пожаловать", "uni", 120, (255, 255, 255)),
        (430, "Магазин открыт", "uni", 90, (255, 230, 200)),
        (650, "欢迎光临", "cjk", 80, (255, 255, 255)),
    ])
    card("04_乌克兰语横幅.png", (1400, 700), ((250, 200, 60), (230, 150, 30)), [
        (150, "Ласкаво просимо", "uni", 130, (60, 30, 10)),
        (400, "Відчинено щодня", "uni", 90, (60, 30, 10)),
    ])
    im, d = card("05_小字西班牙语_需放大.jpg", (3200, 2200), ((30, 60, 120), (10, 20, 50)), [
        (700, "夏季新品发布会", "cjk", 260, (255, 255, 255)),
        (1100, "2026 SUMMER COLLECTION", "latin", 120, (200, 220, 255)),
    ])
    d.text((2560, 2110), "Salida de emergencia · Prohibido fumar", font=font("latin_r", 22), fill=(190, 200, 220))
    im.save(os.path.join(OUT, "05_小字西班牙语_需放大.jpg"), quality=92)
    card("06_中英日韩_不应命中.png", (1400, 1000), ((245, 245, 245), (225, 228, 235)), [
        (120, "欢迎光临", "cjk", 110, (30, 30, 30)),
        (330, "Welcome to our store", "latin", 80, (30, 30, 30)),
        (520, "いらっしゃいませ", "ja", 90, (30, 30, 30)),
        (720, "어서 오세요", "ko", 90, (30, 30, 30)),
    ])
    card("07_英文_不应命中.png", (1400, 800), ((10, 10, 10), (40, 40, 40)), [
        (180, "SUMMER SALE", "latin", 150, (255, 80, 80)),
        (420, "Up to 50% off · Free shipping", "latin_r", 70, (255, 255, 255)),
    ])
    with open(os.path.join(OUT, "08_越南语文案.txt"), "w", encoding="utf-8") as f:
        f.write("Chào mừng bạn đến với cửa hàng của chúng tôi.\nGiảm giá 50% cho tất cả sản phẩm hôm nay.\n")
    print("已生成：", sorted(os.listdir(OUT)))


if __name__ == "__main__":
    main()
