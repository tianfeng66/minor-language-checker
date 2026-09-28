"""生成拉丁字母外语词表：某词在语言 L 中的词频显著高于英语时收录，按差值分三档权重。

用法：pip install --target _build/wordfreq wordfreq && runtime/python/bin/python3 tools/build_lexicon.py
"""
import json
import os
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_build", "wordfreq"))
from wordfreq import top_n_list, zipf_frequency  # noqa: E402

LANGS = ["fr", "de", "es", "it", "pt", "nl", "sv", "da", "nb", "fi", "pl", "cs", "sk", "ro",
         "hu", "tr", "id", "ms", "vi", "ca", "hr", "sl", "lt", "lv", "is", "fil"]
TOP_N = 5000
TIERS = [(2.5, 3), (1.6, 2), (1.0, 1)]

LATIN_WORDS = """
anno domini dei deo deus dominus dominis domino gloria et in est sunt hic iacet jacet requiescat pace
pax vobis ave maria gratia plena sancta sanctus sancti sanctae beata beatus beati mater pater filius
spiritus sacra sacrum templum ecclesia ecclesiae opus fecit aedificavit restauravit anno mdcc memoriae
memoria aeternae aeterna perpetua perpetuam urbi orbi senatus populus que populusque romanus imperator
caesar augustus rex regina regis magnus maximus pontifex fides spes caritas veritas virtus libertas
lux lucis vita vitae mors mortis amor omnia vincit ora pro nobis agnus miserere nostri laus laudate
dominum salve regina coeli caeli terra terrae mundi mundus sic transit tempus fugit carpe diem ars
artis longa brevis quod quae qui cuius cui quem quam per ad ab ex de cum sine sub super ante post inter
ubi ibi nunc semper numquam iam etiam atque sed aut vel non nisi enim nam ergo igitur itaque tamen
civitas civitatis patria patriae gens gentis honor honoris gloriae victoria pro patria mori dulce
decorum carolo carolus alexandro alexander ludovicus ludovico philippus gulielmus mdcccxx
""".split()


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def main():
    out = {}
    for lang in LANGS:
        tiers = {3: [], 2: [], 1: []}
        seen = set()
        for w in top_n_list(lang, TOP_N):
            if len(w) < 2 or not w.isalpha() or w in seen:
                continue
            seen.add(w)
            base = strip_accents(w)
            d = zipf_frequency(w, lang) - max(zipf_frequency(w, "en"), zipf_frequency(base, "en"))
            for th, t in TIERS:
                if d >= th:
                    tiers[t].append(w)
                    break
        out[lang] = [" ".join(tiers[3]), " ".join(tiers[2]), " ".join(tiers[1])]
        print(lang, {k: len(v) for k, v in tiers.items()}, file=sys.stderr)
    out["la"] = [" ".join(w for w in LATIN_WORDS if zipf_frequency(w, "en") < 3.0), "", ""]
    js = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(ROOT, "engine", "lexicon.json"), "w", encoding="utf-8") as f:
        f.write(js)
    print("bytes", len(js.encode("utf-8")), file=sys.stderr)


if __name__ == "__main__":
    main()
