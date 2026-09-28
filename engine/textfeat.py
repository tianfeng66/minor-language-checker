"""文本特征：文字系统统计、外语词表、变音字母、拼音保护。"""
import json
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths  # noqa: E402,F401
import regex  # noqa: E402

LANG_NAMES = {
    "fr": "法语", "de": "德语", "es": "西班牙语", "it": "意大利语", "pt": "葡萄牙语", "nl": "荷兰语",
    "sv": "瑞典语", "da": "丹麦语", "nb": "挪威语", "nn": "挪威语", "fi": "芬兰语", "pl": "波兰语",
    "cs": "捷克语", "sk": "斯洛伐克语", "ro": "罗马尼亚语", "hu": "匈牙利语", "tr": "土耳其语",
    "id": "印尼语", "ms": "马来语", "vi": "越南语", "ca": "加泰罗尼亚语", "hr": "克罗地亚语",
    "bs": "波斯尼亚语", "sl": "斯洛文尼亚语", "lt": "立陶宛语", "lv": "拉脱维亚语", "et": "爱沙尼亚语",
    "is": "冰岛语", "tl": "菲律宾语", "fil": "菲律宾语", "la": "拉丁语", "sq": "阿尔巴尼亚语",
    "eu": "巴斯克语", "cy": "威尔士语", "ga": "爱尔兰语", "af": "南非荷兰语", "sw": "斯瓦希里语",
    "eo": "世界语", "ru": "俄语", "uk": "乌克兰语", "be": "白俄罗斯语", "bg": "保加利亚语",
    "sr": "塞尔维亚语", "mk": "马其顿语", "kk": "哈萨克语", "mn": "蒙古语", "ar": "阿拉伯语",
    "fa": "波斯语", "ur": "乌尔都语", "he": "希伯来语", "el": "希腊语", "th": "泰语", "lo": "老挝语",
    "km": "高棉语", "my": "缅甸语", "hi": "印地语", "bn": "孟加拉语", "ta": "泰米尔语",
    "te": "泰卢固语", "kn": "卡纳达语", "ml": "马拉雅拉姆语", "gu": "古吉拉特语", "pa": "旁遮普语",
    "si": "僧伽罗语", "bo": "藏文", "ka": "格鲁吉亚语", "hy": "亚美尼亚语", "am": "阿姆哈拉语",
    "other": "其他文字", "latin?": "外语(拉丁字母)",
}

SCRIPTS = {
    "Cyrillic": "ru", "Greek": "el", "Arabic": "ar", "Hebrew": "he", "Thai": "th", "Lao": "lo",
    "Khmer": "km", "Myanmar": "my", "Devanagari": "hi", "Bengali": "bn", "Tamil": "ta",
    "Telugu": "te", "Kannada": "kn", "Malayalam": "ml", "Gujarati": "gu", "Gurmukhi": "pa",
    "Sinhala": "si", "Tibetan": "bo", "Georgian": "ka", "Armenian": "hy", "Ethiopic": "am",
    "Mongolian": "mn",
}
_SCRIPT_RE = [(s, regex.compile(r"\p{Script=%s}" % s)) for s in SCRIPTS]
_RE_LATIN = regex.compile(r"\p{Script=Latin}")
_RE_HAN = regex.compile(r"[\p{Script=Han}\p{Script=Bopomofo}]")
_RE_KANA = regex.compile(r"[\p{Script=Hiragana}\p{Script=Katakana}]")
_RE_HANGUL = regex.compile(r"\p{Script=Hangul}")

# 与拉丁字母同形、OCR 易误出的字母
CONFUSABLE = set("АВЕКМНОРСТХаеорсухІіЈјЅѕΑΒΕΖΗΙΚΜΝΟΡΤΥΧοιν")
HALLUCINATION_PRONE = {"Thai", "Arabic", "Hebrew", "Lao", "Khmer", "Myanmar"}


def script_of(ch):
    if not ch.isalpha():
        return None
    if _RE_LATIN.match(ch):
        return "Latin"
    if _RE_HAN.match(ch):
        return "Han"
    if _RE_KANA.match(ch):
        return "Kana"
    if _RE_HANGUL.match(ch):
        return "Hangul"
    for s, r in _SCRIPT_RE:
        if r.match(ch):
            return s
    return "Other"


def refine_script_lang(script, text):
    if script == "Cyrillic":
        for pat, lang in (("[іїєґІЇЄҐ]", "uk"), ("[ўЎ]", "be"), ("[ђћљњџЂЋЉЊЏ]", "sr"),
                          ("[ѓќѕЃЌЅ]", "mk"), ("[әғқңөұүһӘҒҚҢӨҰҮҺ]", "kk")):
            if regex.search(pat, text):
                return lang
        return "ru"
    if script == "Arabic":
        if regex.search("[ٹڈڑںےھ]", text):
            return "ur"
        if regex.search("[پچژگ]", text):
            return "fa"
        return "ar"
    return SCRIPTS.get(script, "other")


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _load_lexicon():
    with open(os.path.join(HERE, "lexicon.json"), encoding="utf-8") as f:
        raw = json.load(f)
    lex = {}
    for lang, tiers in raw.items():
        for tier, words in zip((3, 2, 1), tiers):
            for w in words.split():
                k = strip_accents(w)
                d = lex.setdefault(k, {})
                d[lang] = max(d.get(lang, 0), tier)
    return lex


LEXICON = _load_lexicon()

# 招牌常见、但英语里也借用而未被词频法收录的外语词（权重档 2）
SIGN_WORDS = {
    "fr": "brasserie boulangerie patisserie fromagerie chocolaterie boucherie charcuterie epicerie "
          "confiserie tabac pharmacie rue galerie bistrot boulevard quai sortie entree ferme ouvert soldes "
          "librairie bouquinerie coiffeur parfumerie creperie traiteur caviste mairie gare interdit sauf "
          "vendre louer bourse",
    "de": "strasse platz bahnhof ausgang eingang apotheke backerei konditorei gasthaus gaststatte "
          "rathaus kirche markt bierstube kneipe metzgerei offen geschlossen",
    "es": "calle plaza avenida farmacia panaderia salida entrada cerveceria taberna meson abierto cerrado",
    "it": "piazza trattoria osteria gelateria pasticceria uscita entrata farmacia chiuso aperto via",
    "nl": "straat gracht plein apotheek bakkerij ingang uitgang winkel",
    "pt": "rua praca farmacia padaria saida entrada",
}
for _lang, _words in SIGN_WORDS.items():
    for _w in _words.split():
        _d = LEXICON.setdefault(_w, {})
        _d[_lang] = max(_d.get(_lang, 0), 2)


def _variants(k):
    yield k
    if "v" in k and "u" not in k and len(k) >= 3:
        yield k.replace("v", "u")
    if any(x in k for x in ("oe", "ue", "ae")):
        yield k.replace("oe", "o").replace("ue", "u").replace("ae", "a")


def _merged_hits(part):
    out = {}
    for v in _variants(part):
        if len(v) >= 4 and v in LEXICON:
            for lang, t in LEXICON[v].items():
                out[lang] = max(out.get(lang, 0), t)
    return out


def lex_lookup(word):
    k = strip_accents(word.lower())
    for v in _variants(k):
        hit = LEXICON.get(v)
        if hit:
            return hit
    for kk in ((k, k[1:]) if len(k) >= 10 else (k,)) if len(k) >= 9 else ():
        for i in range(4, len(kk) - 3):
            a = _merged_hits(kk[:i])
            b = _merged_hits(kk[i:])
            if a and b:
                common = {lang: min(a[lang], b[lang]) for lang in a if lang in b}
                if common:
                    return common
    return None


_DIAC = {
    "ñ": "es", "ß": "de", "ø": "da nb", "æ": "da nb is", "å": "sv da nb", "ä": "de sv fi",
    "ö": "de sv fi tr hu", "ü": "de tr hu", "ç": "fr pt tr ca", "ã": "pt", "õ": "pt", "ş": "tr ro",
    "ğ": "tr", "ł": "pl", "ś": "pl", "ź": "pl", "ż": "pl", "ą": "pl", "ę": "pl",
    "ń": "pl", "č": "cs sk hr", "š": "cs sk hr", "ž": "cs sk hr", "ř": "cs", "ů": "cs", "ě": "cs",
    "ő": "hu", "ű": "hu", "ă": "ro", "ș": "ro", "ț": "ro", "đ": "vi hr", "þ": "is", "ð": "is",
    "œ": "fr", "é": "fr es pt", "è": "fr it", "ê": "fr pt", "ë": "fr nl", "à": "fr it pt",
    "â": "fr pt", "î": "fr ro", "ï": "fr", "ô": "fr pt", "û": "fr", "ù": "fr", "ì": "it",
    "ò": "it", "á": "es pt cs hu", "í": "es pt cs hu", "ó": "es pt pl", "ú": "es pt cs",
}
_VI = regex.compile("[ơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]")


def diacritic_langs(word):
    w = word.lower()
    if _VI.search(w):
        return ["vi"]
    out = []
    for ch in w:
        for lang in _DIAC.get(ch, "").split():
            if lang not in out:
                out.append(lang)
    return out


_INI = "zh ch sh b p m f d t n l g k h j q x r z c s y w".split() + [""]
_FIN = ("a o e i u v ai ei ao ou an en ang eng ong er ia ie iao iu ian in iang ing iong "
        "ua uo uai ui uan un uang ve ue").split()
_SYL = {i + f for i in _INI for f in _FIN} | set(
    "wai wei wan wen wang weng yan yin yang ying yong yue yuan yun you yao ye "
    "hong kong wah nam tsim sha tsui wong cheung leung chan lam lau yau hsin tsai".split())


with open(os.path.join(HERE, "pinyin_syl.txt"), encoding="utf-8") as _f:
    _SYL = set(_f.read().split())


def is_pinyin(word):
    w = strip_accents(word.lower()).replace("ü", "v")
    if not w.isascii() or not w.isalpha() or len(w) < 2 or len(w) > 18:
        return False
    ok = [True] + [False] * len(w)
    for e in range(1, len(w) + 1):
        for s in range(max(0, e - 6), e):
            if ok[s] and w[s:e] in _SYL and (s == 0 or w[s] not in "aoe"):
                ok[e] = True
                break
    return ok[-1]


FUNCTION_WORDS = {
    "fr": "de la le les du des au aux et une sur pour avec chez dans",
    "es": "el los las del de y para",
    "it": "il lo di da del della dei nel alla",
    "pt": "os dos das da de em",
    "de": "der das und zum zur ein eine von mit fur auf",
    "nl": "de het een voor",
    "sv": "och av ett till",
    "da": "og af til",
    "nb": "og av til",
    "la": "et cum",
}
_FW = {}
for _lang, _ws in FUNCTION_WORDS.items():
    for _w in _ws.split():
        _FW.setdefault(strip_accents(_w), set()).add(_lang)


URL_EMAIL = regex.compile(r"\S+@\S+|https?://\S+|www\.\S+|\S+\.(?:com|net|org|cn|de|fr|io)\b", regex.I)


def function_word_langs(text):
    """返回 {lang: 个数}，统计外语功能词（de/la/der/und…）。"""
    out = {}
    for w in regex.findall(r"\p{L}+", text.lower()):
        for lang in _FW.get(strip_accents(w), ()):
            out[lang] = out.get(lang, 0) + 1
    return out
