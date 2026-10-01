"""
Text processing and similarity clustering utilities for e-commerce product titles.
"""

import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Set, Any


# Common marketing noise patterns in live/short-video e-commerce titles
NOISE_BRACKET_PATTERNS = [
    r"【[^】]*?(?:爆款|热销|正品|官方|包邮|特惠|限时|抢购|拍|送|减|买|同款|推荐|专享|福利|现货|速发|冲量|自营|旗舰|精选|新品|狂欢|回购|好物|主播|破价|亏本|秒杀|补贴)[^】]*?】",
    r"\[[^\]]*?(?:爆款|热销|正品|官方|包邮|特惠|限时|抢购|拍|送|减|买|同款|推荐|专享|福利|现货|速发|冲量|自营|旗舰|精选|新品|狂欢|回购|好物|主播|破价|亏本|秒杀|补贴)[^\]]*?\]",
    r"（[^）]*?(?:包邮|正品|送|拍|现货|特惠|专享)[^）]*?）",
    r"\([^\)]*?(?:包邮|正品|送|拍|现货|特惠|专享)[^\)]*?\)",
]

# Specific promo keywords to remove
NOISE_KEYWORDS = [
    r"官方旗舰店",
    r"正品保证",
    r"假一赔十",
    r"全国包邮",
    r"限时秒杀",
    r"拍\s*[1-9一二三四五]\s*发\s*[1-9一二三四五六七八九十]+",
    r"拍\s*[1-9一二三四五]\s*件\s*起",
    r"买\s*[1-9一二三四五]\s*送\s*[1-9一二三四五]+",
    r"买一送一",
    r"买二送三",
    r"网红同款",
    r"明星推荐",
    r"主播力荐",
    r"热卖爆款",
    r"爆单推荐",
    r"现货速发",
    r"顺丰包邮",
    r"今日特价",
    r"专柜正品",
    r"工厂直发",
    r"断货王",
    r"回购率高",
    r"超值特惠",
    r"拍下立减",
    r"抢完即止",
    r"狂欢价",
    r"秒杀价",
    r"领券立减",
    r"第二件半价",
    r"第二件0元",
    r"全网热销",
]

# Symbols / emojis regex
SYMBOLS_RE = re.compile(
    r"[\s\-_——\|\/\\★☆◆◇●○▲△▼▽【】\[\]（）\(\)《》「」" "''“”‘’!！?？~～#]+", re.UNICODE
)


def clean_product_title(title: str) -> str:
    """
    Clean promotional noise and marketing words from a product title.
    Example:
      '【官方正品 包邮】超能植翠低泡洗衣液3kg 拍1发2' -> '超能植翠低泡洗衣液3kg'
    """
    if not title:
        return ""

    cleaned = title.strip()

    # 1. Remove bracketed promo sections
    for pat in NOISE_BRACKET_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # 2. Remove isolated promo keywords
    for kw in NOISE_KEYWORDS:
        cleaned = re.sub(kw, "", cleaned, flags=re.IGNORECASE)

    # 3. Clean leading / trailing leftover brackets and punctuation
    cleaned = re.sub(r"^[【\[\(（]+", "", cleaned)
    cleaned = re.sub(r"[】\]\)）]+$", "", cleaned)

    # 4. Collapse multiple spaces and symbols
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 5. If over-cleaned to empty, fallback to basic stripped original
    if not cleaned:
        cleaned = re.sub(r"\s+", " ", title).strip()

    return cleaned


def get_character_ngrams(text: str, n: int = 2) -> Set[str]:
    """Generate character n-grams from text."""
    text = SYMBOLS_RE.sub("", text).lower()
    if len(text) <= n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def calculate_jaccard_similarity(text1: str, text2: str, n: int = 2) -> float:
    """Calculate character n-gram Jaccard similarity."""
    ngrams1 = get_character_ngrams(text1, n)
    ngrams2 = get_character_ngrams(text2, n)
    if not ngrams1 or not ngrams2:
        return 0.0
    intersection = ngrams1.intersection(ngrams2)
    union = ngrams1.union(ngrams2)
    return len(intersection) / len(union)


@lru_cache(maxsize=4096)
def prepared_title(title: str):
    cleaned = clean_product_title(title).lower()
    return cleaned, frozenset(get_character_ngrams(cleaned))


def calculate_string_similarity(
    title1: str, title2: str, *, minimum: float = 0.0
) -> float:
    """
    Calculate combined similarity score between two product titles (0.0 to 1.0).
    Combines cleaned text exact match, SequenceMatcher ratio, and n-gram Jaccard.
    """
    if not title1 or not title2:
        return 0.0

    t1_clean, grams1 = prepared_title(title1)
    t2_clean, grams2 = prepared_title(title2)

    if t1_clean == t2_clean:
        return 1.0

    # If one is a complete substring of another and length ratio is high
    short_len = min(len(t1_clean), len(t2_clean))
    long_len = max(len(t1_clean), len(t2_clean))
    if short_len >= 4 and (t1_clean in t2_clean or t2_clean in t1_clean):
        ratio = short_len / long_len
        if ratio >= 0.5:
            # High substring containment boost
            return round(0.75 + 0.25 * ratio, 4)

    # SequenceMatcher ratio
    intersection = len(grams1 & grams2)
    union = len(grams1) + len(grams2) - intersection
    jaccard_ratio = intersection / union if union else 0.0
    matcher = SequenceMatcher(None, t1_clean, t2_clean)
    # quick_ratio is an upper bound, not a replacement score. Account for
    # round(..., 4) so pruning cannot change threshold or tie decisions.
    if (
        minimum > 0
        and 0.5 * matcher.quick_ratio() + 0.5 * jaccard_ratio + 0.00005 < minimum
    ):
        return 0.0
    sm_ratio = matcher.ratio()

    # Weighted score
    combined = 0.5 * sm_ratio + 0.5 * jaccard_ratio
    return round(combined, 4)


def are_products_identical(title1: str, title2: str, threshold: float = 0.75) -> bool:
    """Determine if two product titles represent the same product."""
    sim = calculate_string_similarity(title1, title2)
    return sim >= threshold


def parse_chinese_count_str(val: Any) -> int:
    """
    Parse numbers that might be formatted as strings with Chinese units (万, 亿, w, etc.).
    Examples:
      '1.2万' -> 12000
      '3500w' -> 35000000
      '1000+' -> 1000
      '1,234' -> 1234
      '获赞 3.5万' -> 35000
      12345 -> 12345
    """
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        try:
            return int(val)
        except (ValueError, OverflowError):
            return 0

    s = str(val).strip().replace(",", "")
    if not s:
        return 0

    m = re.search(r"(\d+(?:\.\d+)?)\s*([万wW亿yY])?", s)
    if not m:
        return 0

    num_str, unit = m.group(1), m.group(2)
    try:
        base = float(num_str)
    except ValueError:
        return 0

    if unit in ("万", "w", "W"):
        return int(base * 10_000)
    elif unit in ("亿", "y", "Y"):
        return int(base * 100_000_000)
    return int(base)
