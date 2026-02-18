import re
from dataclasses import dataclass


@dataclass
class Candidate:
    title: str
    magnet_or_torrent: str


def extract_season_no(title: str) -> int | None:
    patterns = [
        r"\bS0?([1-9]\d?)E\d{1,3}\b",
        r"\bS(?:EASON)?\s?0?([1-9]\d?)\b",
        r"\b([1-9]\d?)(?:st|nd|rd|th)\s+season\b",
        r"第\s?0?([1-9]\d?)\s?[季期]",
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            s = int(m.group(1))
            if 1 <= s <= 30:
                return s
    return None


def extract_episode_no(title: str) -> int | None:
    # Common explicit forms first: S01E03 / EP03 / 第3话 / 第03集
    patterns = [
        r"\bS\d{1,2}E(\d{1,3})\b",
        r"\b(?:E|EP)\s?0?(\d{1,3})\b",
        r"第\s?0?(\d{1,3})\s?[话話集]",
        r"(?:\[|\s|-)0?(\d{1,3})(?:v\d+)?(?:\]|\s|$)",
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            ep = int(m.group(1))
            # Reject episode 0 (often from WebRip splits) and out-of-range
            if 1 <= ep <= 300:
                return ep

    # Last resort: standalone number, excluding common non-episode numbers.
    # Avoid accidental matches like 1080p, x265, 10bit, years, etc.
    bad_numbers = {264, 265, 480, 540, 576, 720, 1080, 1440, 2160}
    for m in re.finditer(r"\b(\d{1,4})\b", title):
        n = int(m.group(1))
        if n in bad_numbers:
            continue
        if 1900 <= n <= 2100:  # likely year
            continue
        # Reject episode 0 and out-of-range
        if 1 <= n <= 300:
            return n
    return None


def _norm(s: str) -> str:
    x = s.lower()
    x = x.replace("2nd season", "s2").replace("3rd season", "s3")
    x = x.replace("second season", "s2").replace("third season", "s3")
    x = x.replace("第2季", "s2").replace("第二季", "s2").replace("第3季", "s3").replace("第三季", "s3")
    x = re.sub(r"[^\w\u4e00-\u9fff]+", " ", x)
    return re.sub(r"\s+", " ", x).strip()


_TOKEN_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "season",
    "part",
    "episode",
    "no",
    "ko",
}


def _alias_match_score(title: str, aliases: list[str]) -> int:
    nt = _norm(title)
    # Sort aliases: prioritize shorter ones (typically more canonical) to avoid
    # substring false positives from long aliases containing the canonical name.
    sorted_aliases = sorted(aliases, key=lambda a: (len(a), a))
    for a in sorted_aliases:
        na = _norm(a)
        if not na:
            continue
        if na in nt:
            return 40

        # Conservative fuzzy overlap fallback (avoid false positives like
        # matching generic tokens such as "no"/"ko").
        ta = {
            tok
            for tok in na.split(" ")
            if len(tok) >= 3 and tok not in _TOKEN_STOPWORDS and not tok.isdigit()
        }
        if len(ta) < 2:
            continue

        tt = set(nt.split(" "))
        overlap = len(ta & tt)
        if overlap >= 2:
            return 30
    return 0


def is_bad_release(title: str) -> bool:
    t = title.lower()
    bad_keywords = [
        'camrip', 'hdcam', 'telesync', 'ts ', 'telecine',
        'screen record', 'screenrec', 'handcam',
        'theaniplex.in',
        'fanart corner', 'fanart', 'creditless', 'nced', 'ncop',
        'preview', 'pv ', ' pv', 'trailer', 'cm ', ' cm',
        'menu', 'bonus', 'extra', 'special', 'ova ',
    ]
    return any(k in t for k in bad_keywords)


def score_release(title: str, aliases: list[str], ep_no: int, preferred_subgroups: list[str]) -> int:
    t = title.lower()
    score = 0
    score += _alias_match_score(title, aliases)
    parsed_ep = extract_episode_no(title)
    if parsed_ep == ep_no:
        score += 40
    if any(sg.lower() in t for sg in preferred_subgroups if sg):
        score += 20
    if "1080" in t:
        score += 10
    return score
