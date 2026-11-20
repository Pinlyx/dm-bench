"""A small, dependency-free language guesser for the languages dm-bench covers.

It is deliberately simple: script detection for Russian (Cyrillic) and Arabic,
then stopword and diacritic scoring for the Latin-script languages. It is good
enough to tell "the agent answered in Turkish" from "the agent answered in
English" on a normal customer reply of a sentence or more. It is not a general
purpose language identifier and it will be unreliable on one or two words.
"""

import re
from typing import Dict, Optional

SUPPORTED = ("en", "tr", "es", "ru", "de", "pt", "ar")

# Function words that are frequent in customer-service replies and, as far as
# possible, distinctive for one language. Words shared by several languages
# (for example "de", "que", "para") are left out on purpose.
STOPWORDS: Dict[str, frozenset] = {
    "en": frozenset(
        """the and is are you your we our to for of with can will please thanks thank
        it this that be have has not if at on in or as an hi hello sorry would could
        let me know there what when how which they from just so i'm we'll we're you're
        it's don't can't sure here help happy""".split()
    ),
    "tr": frozenset(
        """ve bir bu için ile mı mu mü çok merhaba teşekkür teşekkürler size sizin
        siz biz bizim ama veya daha gibi olarak var yok değil şu ne nasıl hemen
        lütfen evet hayır tabii ki kadar sonra önce hangi rica ederiz edebilirim
        yardımcı olabilirim olur iyi günler""".split()
    ),
    "es": frozenset(
        """el los las del y es por usted ustedes su sus pero está están muy gracias
        hola puedo tenemos le lo una uno al también nuestro nuestra hay
        cuando cómo qué sí ayudarte ayudarle con voy ya aquí tu tus""".split()
    ),
    "pt": frozenset(
        """o os não você vocês é uma um com obrigado obrigada olá posso temos
        também são ao da dos das em na nas seu sua nosso nossa muito
        quando como sim ajudar então vou já pra seus suas aqui""".split()
    ),
    "de": frozenset(
        """der die das und ist nicht sie ich wir ihr ihnen ihre mit für auf gerne
        danke bitte ein eine einen dem den des zu bei auch noch sind haben wir
        können kann wenn wie oder aber hallo vielen gern uns unser unsere""".split()
    ),
}

# Characters that strongly suggest one Latin-script language.
DIACRITICS: Dict[str, str] = {
    "tr": "ıİğĞşŞ",
    "es": "ñÑ¿¡",
    "pt": "ãõÃÕ",
    "de": "ßẞ",
}

_URL = re.compile(r"https?://\S+|www\.\S+|\S+@\S+")
_MARKER = re.compile(r"\[HANDOFF(?::[^\]]*)?\]", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


def _is_cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ӿ"


def _is_arabic(ch: str) -> bool:
    return "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ" or "ﭐ" <= ch <= "﻿"


def scores(text: str) -> Dict[str, float]:
    """Return a score per supported language. Higher means more likely."""
    clean = _MARKER.sub(" ", _URL.sub(" ", text or ""))
    letters = [c for c in clean if c.isalpha()]
    result = {lang: 0.0 for lang in SUPPORTED}
    if not letters:
        return result
    cyr = sum(1 for c in letters if _is_cyrillic(c))
    ara = sum(1 for c in letters if _is_arabic(c))
    total = len(letters)
    result["ru"] = 100.0 * cyr / total
    result["ar"] = 100.0 * ara / total
    latin_share = 1.0 - (cyr + ara) / total
    if latin_share <= 0:
        return result
    words = [w.lower() for w in _WORD.findall(clean)]
    for lang, words_set in STOPWORDS.items():
        hits = sum(1 for w in words if w in words_set)
        bonus = sum(3 for c in clean if c in DIACRITICS.get(lang, ""))
        result[lang] = (hits + bonus) * latin_share
    return result


def detect(text: str) -> Optional[str]:
    """Best-guess language code, or None when there is no usable signal."""
    s = scores(text)
    if s["ru"] >= 50.0:
        return "ru"
    if s["ar"] >= 50.0:
        return "ar"
    latin = {k: v for k, v in s.items() if k not in ("ru", "ar")}
    best = max(latin, key=lambda k: latin[k])
    if latin[best] <= 0:
        return None
    return best
