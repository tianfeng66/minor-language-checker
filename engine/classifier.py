"""小语种判定：OCR 文本行 → 小语种(确定/疑似) / 非小语种，并生成备注。"""
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import paths  # noqa: E402,F401
import regex  # noqa: E402

import textfeat as tf  # noqa: E402

LINGUA_LANGS = ["ENGLISH", "FRENCH", "GERMAN", "SPANISH", "ITALIAN", "PORTUGUESE", "DUTCH", "SWEDISH",
                "DANISH", "BOKMAL", "NYNORSK", "FINNISH", "POLISH", "CZECH", "SLOVAK", "ROMANIAN",
                "HUNGARIAN", "TURKISH", "INDONESIAN", "MALAY", "VIETNAMESE", "CATALAN", "CROATIAN",
                "BOSNIAN", "SLOVENE", "LITHUANIAN", "LATVIAN", "ESTONIAN", "ICELANDIC", "TAGALOG",
                "LATIN", "ALBANIAN", "BASQUE", "WELSH", "IRISH", "AFRIKAANS", "SWAHILI", "ESPERANTO"]
FT_ALIAS = {"no": "nb", "nn": "nb", "sh": "hr", "bs": "hr"}

SENS = {"strict": 1.5, "normal": 1.0, "loose": 0.6}
TIER_W = {3: 1.0, 2: 0.6, 1: 0.3}
_WORD = regex.compile(r"\p{L}+(?:['’]\p{L}+)?")
_ELISION = regex.compile(r"^(l|d|qu|j|n|s|c|m|t|dell|nell|all|sull)['’](\p{L}{2,})$", regex.I)


class LangID:
    """lingua + fastText 双模型投票。"""

    def __init__(self):
        self.lingua = self.ft = None
        errors = []
        try:
            from lingua import Language, LanguageDetectorBuilder
            langs = [getattr(Language, n) for n in LINGUA_LANGS if hasattr(Language, n)]
            self.lingua = LanguageDetectorBuilder.from_languages(*langs).with_preloaded_language_models().build()
        except Exception as e:  # noqa: BLE001
            errors.append("lingua：%s" % e)
        try:
            import fasttext_pybind  # 直接用底层接口，免去 fasttext 包装层对 numpy 的依赖
            self.ft = fasttext_pybind.fasttext()
            self.ft.loadModel(os.path.join(HERE, "..", "models", "lid.176.ftz"))
        except Exception as e:  # noqa: BLE001
            errors.append("fastText：%s" % e)
        if not (self.lingua or self.ft):
            raise RuntimeError("语言模型加载失败：" + "；".join(errors))
        self.warnings = errors
        self.w = 0.5 if (self.lingua and self.ft) else 1.0

    def __call__(self, text):
        t = text.lower().replace("\n", " ").strip()
        scores = defaultdict(float)
        if not t:
            return []
        if self.lingua:
            for c in self.lingua.compute_language_confidence_values(t)[:4]:
                code = c.language.iso_code_639_1.name.lower()
                scores[FT_ALIAS.get(code, code)] += c.value * self.w
        if self.ft:
            for p, lab in self.ft.predict(t + "\n", 4, 0.0, "strict"):
                code = lab.replace("__label__", "")
                scores[FT_ALIAS.get(code, code)] += float(p) * self.w
        return sorted(scores.items(), key=lambda x: -x[1])


_LID = None


def get_lid():
    global _LID
    if _LID is None:
        _LID = LangID()
    return _LID


def conf_weight(conf):
    return 1.0 if conf >= 0.95 else (0.6 if conf >= 0.5 else 0.3)


def script_hit(script, n, distinct, frac, conf, exact):
    if exact:
        return "strong" if n >= 2 else None
    if script in ("Cyrillic", "Greek"):
        if distinct >= 3 and n >= 4 and frac >= 0.5 and (conf >= 0.95 or n >= 6):
            return "strong"
        if distinct >= 2 and n >= 3 and frac >= 0.4:
            return "weak"
        return None
    if script in tf.HALLUCINATION_PRONE:
        if (n >= 4 and frac >= 0.6 and conf >= 0.5) or (n >= 8 and frac >= 0.7):
            return "strong"
        if n >= 3 and frac >= 0.5 and conf >= 0.5:
            return "weak"
        return None
    if n >= 3 and frac >= 0.5:
        return "strong" if conf >= 0.5 else "weak"
    return None


def latin_evidence(text):
    """返回 [(词, {lang: 权重}, 是否有变音)]。"""
    out = []
    for word in _WORD.findall(text):
        langs = {}
        m = _ELISION.match(word)
        core = m.group(2) if m else word
        if m:
            langs["fr"] = langs.get("fr", 0) + 0.8
            langs["it"] = langs.get("it", 0) + 0.4
        if len(core) >= 4 and tf.is_pinyin(core):
            continue
        lf = 0.35 if len(core) == 2 else 0.6 if len(core) == 3 else 1.0 if len(core) < 7 else 1.3
        lex = tf.lex_lookup(core) if len(core) >= 2 else None
        if lex:
            for lang, tier in lex.items():
                langs[lang] = langs.get(lang, 0) + TIER_W[tier] * lf
        diac = tf.diacritic_langs(core) if len(core) >= 3 else []
        for lang in diac:
            langs[lang] = langs.get(lang, 0) + 0.8
        if langs and (len(core) >= 3 or m):
            out.append((word, langs, bool(diac)))
    return out
