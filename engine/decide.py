"""整张图/整个文件的汇总判定。"""
from collections import defaultdict

import textfeat as tf
import regex
from classifier import SENS, conf_weight, get_lid, latin_evidence, script_hit

EN_LIKE = {"en"}
NOT_FOREIGN = {"en", "zh", "ja", "ko", "yue", "wuu"}
CYRILLIC_ABSENT = {"uk": "[ыэъёЫЭЪЁ]", "be": "[ищъИЩЪ]", "sr": "[ёйщъыьэюяЁЙЩЪЫЬЭЮЯ]",
                   "mk": "[ёйщъыьэюяЁЙЩЪЫЬЭЮЯ]"}


def english_prob(guess):
    return next((p for lang, p in guess if lang == "en"), 0.0)


def foreign_top(guess):
    for lang, p in guess:
        if lang in NOT_FOREIGN:
            continue
        if lang in tf.LANG_NAMES:
            return lang, p
    return None, 0.0


def analyze(items, exact=False, sensitivity="normal"):
    """items: [{text, conf, box?}]；exact=True 表示文本来自文本文件（无 OCR 误差）。"""
    k = SENS.get(sensitivity, 1.0)
    lid = get_lid()
    lang_score = defaultdict(float)
    lang_level = {}
    lang_samples = defaultdict(list)
    marks = []
    present = set()
    latin_texts = []

    def add(lang, level, score, sample, box, reason, conf=1.0, evl=()):
        lang_score[lang] += score
        if level == "strong" or lang not in lang_level:
            lang_level[lang] = level if lang_level.get(lang) != "strong" else "strong"
        if sample not in lang_samples[lang] and len(lang_samples[lang]) < 6:
            lang_samples[lang].append(sample)
        marks.append({"text": sample, "box": box, "lang": lang, "level": level, "reason": reason, "conf": conf, "evl": list(evl)})

    for it in items:
        text = it.get("text", "")
        conf = float(it.get("conf", 1.0))
        box = it.get("box")
        letters = [c for c in text if c.isalpha()]
        if not letters:
            continue
        counts = defaultdict(int)
        distinct = defaultdict(int)
        for c in letters:
            s = tf.script_of(c)
            counts[s] += 1
            if c not in tf.CONFUSABLE:
                distinct[s] += 1
        if conf >= 0.5 or exact:
            if counts["Kana"] >= 2:
                present.add("日文")
            elif counts["Han"] >= 2:
                present.add("中文")
            if counts["Hangul"] >= 2:
                present.add("韩文")
        for s, n in list(counts.items()):
            if s in ("Latin", "Han", "Kana", "Hangul", None):
                continue
            lvl = script_hit(s, n, distinct[s], n / len(letters), conf, exact)
            if lvl and not exact:
                script_letters = [c for c in letters if tf.script_of(c) == s]
                if n >= 6 and len(set(script_letters)) / n < 0.35:
                    lvl = None
                elif lvl == "strong" and (conf < 0.5 or (counts["Latin"] >= 2 and n / len(letters) < 0.8)):
                    lvl = "weak"
            if lvl:
                lang = tf.refine_script_lang(s, text)
                add(lang, lvl, 2.0 * conf_weight(conf) if lvl == "strong" else 0.6, text, box, s, conf)
        if counts["Latin"] >= 3:
            latin_texts.append((text, conf, box))

    en_seen = False
    for text0, conf, box in latin_texts:
        text = tf.URL_EMAIL.sub(" ", text0).strip()
        if sum(c.isalpha() for c in text) < 3:
            continue
        ev = latin_evidence(text)
        w = conf_weight(conf)
        guess = lid(text) if (ev or len(text) >= 8) else []
        raw_top = guess[0][0] if guess else None
        pen = english_prob(guess)
        top, p = foreign_top(guess)
        diac_any = any(d for _, _, d in ev)
        strong_lex = sum(1 for _, langs, _ in ev if max(langs.values()) >= 0.9)
        fw = tf.function_word_langs(text) if ev else {}
        is_en = raw_top in EN_LIKE or pen >= 0.3
        if is_en and not diac_any and strong_lex < 2 and not fw:
            en_seen = True
            continue
        if raw_top in NOT_FOREIGN and raw_top not in EN_LIKE and not ev:
            continue
        if not ev and (p < 0.8 or conf < 0.95 or len(text) < 12):
            continue
        longest = max((len(wd) for wd, _, _ in ev), default=0)
        if len(ev) == 1 and longest < 6 and not diac_any and p < 0.5 and not fw:
            continue
        ev_lang = defaultdict(float)
        for _, langs, _ in ev:
            for lang, sc in langs.items():
                ev_lang[lang] += sc
        for lang, n in fw.items():
            if lang in ev_lang:
                ev_lang[lang] += 0.5 * n
        if top and p >= 0.35:
            lang = top
            score = (ev_lang.get(top, 0) + 0.6 * sum(ev_lang.values()) / max(1, len(ev_lang)) + p) * w
        elif ev_lang:
            lang = max(ev_lang, key=ev_lang.get)
            score = ev_lang[lang] * 0.6 * w
        else:
            continue
        lex_words = sum(1 for wd, _, _ in ev if tf.lex_lookup(regex.sub(r"^\p{L}+['’]", "", wd)))
        diac_lex = any(d and tf.lex_lookup(wd) for wd, _, d in ev)
        solid = (len(ev) >= 2 and lex_words >= 1) or diac_lex or (p >= 0.7 and lex_words >= 1) or (fw and lex_words >= 1 and longest >= 6)
        lvl = "strong" if (score >= 1.6 * k and conf >= 0.5 and solid) else "weak"
        add(lang, lvl, score, text0, box, "lexicon+lid", conf, ev_lang.keys())

    if en_seen:
        present.add("英文")

    # 用全部命中文本再做一次整体语言识别，合并过于零散的拉丁语种归属
    latin_marks = [m for m in marks if m["reason"] == "lexicon+lid"]
    if len(latin_marks) >= 2:
        guess = lid(" ".join(m["text"] for m in latin_marks))
        main, mp = foreign_top(guess)
        if main and guess[0][0] == main and mp >= 0.4:
            for m in latin_marks:
                if lang_score[m["lang"]] < 1.2 * k and m["lang"] != main:
                    lang_score[main] += lang_score.pop(m["lang"], 0)
                    lang_samples[main].extend(s for s in lang_samples.pop(m["lang"], []) if s not in lang_samples[main])
                    if lang_level.pop(m["lang"], None) == "strong":
                        lang_level[main] = "strong"
                    lang_level.setdefault(main, "weak")
                    m["lang"] = main

    latin_marks = [m for m in marks if m["reason"] == "lexicon+lid"]
    if latin_marks:
        top = max({m["lang"] for m in latin_marks}, key=lambda x: lang_score[x])
        for m in latin_marks:
            src = m["lang"]
            if src != top and top in m["evl"] and lang_score[src] < lang_score[top]:
                lang_score[top] += lang_score.pop(src, 0)
                lang_samples[top].extend(x for x in lang_samples.pop(src, []) if x not in lang_samples[top])
                if lang_level.pop(src, None) == "strong":
                    lang_level[top] = "strong"
                for mm in marks:
                    if mm["lang"] == src:
                        mm["lang"] = top

    # 西里尔字母行默认归为俄语；同图已明确出现乌克兰语等，且这些行里没有该语言不用的字母时，归入该语言
    cyr = [x for x in CYRILLIC_ABSENT if x in lang_score]
    if "ru" in lang_score and len(cyr) == 1:
        dst = cyr[0]
        if not any(regex.search(CYRILLIC_ABSENT[dst], m["text"]) for m in marks if m["lang"] == "ru"):
            lang_score[dst] += lang_score.pop("ru")
            lang_samples[dst].extend(x for x in lang_samples.pop("ru", []) if x not in lang_samples[dst])
            if lang_level.pop("ru", None) == "strong":
                lang_level[dst] = "strong"
            for m in marks:
                if m["lang"] == "ru":
                    m["lang"] = dst

    langs = []
    for lang, sc in sorted(lang_score.items(), key=lambda x: -x[1]):
        lvl = lang_level.get(lang, "weak")
        hi_conf = {m["text"] for m in marks if m["lang"] == lang and (m.get("conf") or 0) >= 0.95}
        if lvl == "weak" and (sc >= 3.0 * k or len(hi_conf) >= 3 or (len(hi_conf) >= 2 and sc >= 2.0 * k)):
            lvl = "strong"
        if sc < 0.5 * k:
            continue
        langs.append({"code": lang, "name": tf.LANG_NAMES.get(lang, lang), "level": lvl,
                      "score": round(sc, 2), "samples": lang_samples[lang][:6]})

    strong = [x for x in langs if x["level"] == "strong"]
    verdict = "小语种" if langs else "非小语种"
    level = "确定" if strong else ("疑似" if langs else "")
    note = "；".join(
        "%s(%s)：%s" % (x["name"], "确定" if x["level"] == "strong" else "疑似", " / ".join(x["samples"][:4]))
        for x in langs)
    if not langs:
        note = "未发现小语种" + ("（含%s）" % "、".join(sorted(present)) if present else "（未识别到文字）" if not items else "")
    return {"verdict": verdict, "level": level, "langs": langs, "note": note,
            "present": sorted(present), "marks": [m for m in marks if any(m["lang"] == x["code"] for x in langs)]}
