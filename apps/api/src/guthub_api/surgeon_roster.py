"""Automatic approval of colorectal surgeons (H10 #168, ADR-0022).

An application is approved without the maintainer when both hold:
- the name and hospital appear together on the society's public doctor map (醫師地圖), and
- the applicant signed in through a link mailed to an address at that hospital's domain.

Names and hospitals are public, so the map alone proves nothing; the mailbox does. Only sessions opened from an
emailed link count (JWT amr "otp" or "magiclink"): a password sign-up never proved the address. Anything uncertain,
from an unreadable map to a hospital missing from HOSPITALS or a branch hospital, leaves the application for the
maintainer. The map is read when needed and never stored.
"""

import html
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import requests

ROSTER_URL = "https://www.crs.org.tw/zh-tw/map"
CACHE_SECONDS = 600


@dataclass(frozen=True)
class Hospital:
    label: str
    names: tuple[str, ...]  # any of these within the normalized hospital name picks this hospital
    domains: tuple[str, ...]  # staff mail domains; subdomains count


# Mail domains checked to have MX records and to be the hospital's own site (2026-11-17). A hospital missing here,
# or a branch (分院), never auto-approves: it goes to the maintainer.
HOSPITALS = (
    Hospital("臺北榮民總醫院", ("台北榮民總醫院", "台北榮總", "北榮"), ("vghtpe.gov.tw",)),
    Hospital("臺中榮民總醫院", ("台中榮民總醫院", "台中榮總", "中榮"), ("vghtc.gov.tw",)),
    Hospital("高雄榮民總醫院", ("高雄榮民總醫院", "高雄榮總", "高榮"), ("vghks.gov.tw",)),
    Hospital("臺大醫院", ("台大醫院", "台灣大學醫學院附設醫院"), ("ntuh.gov.tw",)),
    Hospital("長庚紀念醫院", ("長庚",), ("cgmh.org.tw",)),
    Hospital("馬偕紀念醫院", ("馬偕",), ("mmh.org.tw",)),
    Hospital("三軍總醫院", ("三軍總醫院", "三總"), ("ndmctsgh.edu.tw",)),
    Hospital("彰化基督教醫院", ("彰化基督教", "彰基"), ("cch.org.tw",)),
    Hospital("中國醫藥大學附設醫院", ("中國醫藥大學附設醫院", "中國附醫"), ("cmuh.org.tw",)),
    Hospital("高雄醫學大學附設醫院", ("高雄醫學大學附設", "高醫"), ("kmuh.org.tw",)),
    Hospital("奇美醫院", ("奇美",), ("chimei.org.tw",)),
    Hospital("成大醫院", ("成功大學醫學院附設醫院", "成大醫院"), ("hosp.ncku.edu.tw",)),
    Hospital("慈濟醫院", ("慈濟",), ("tzuchi.com.tw",)),
    Hospital("新光醫院", ("新光",), ("skh.org.tw",)),
    Hospital("亞東紀念醫院", ("亞東",), ("femh.org.tw",)),
    Hospital("國泰綜合醫院", ("國泰綜合醫院", "國泰醫院"), ("cgh.org.tw",)),
    Hospital("義大醫院", ("義大",), ("edah.org.tw",)),
    Hospital("光田綜合醫院", ("光田",), ("ktgh.com.tw",)),
    Hospital("童綜合醫院", ("童綜合",), ("sltung.com.tw",)),
    Hospital("嘉義基督教醫院", ("嘉義基督教", "嘉基"), ("cych.org.tw",)),
    Hospital("振興醫院", ("振興",), ("chgh.org.tw",)),
    Hospital("秀傳醫院", ("秀傳",), ("show.org.tw",)),
)

type Roster = list[tuple[str, tuple[str, ...]]]  # (name, hospitals) per doctor on the map


@dataclass(frozen=True)
class Check:
    listed: bool | None  # the map shows this name at this hospital; None when the map could not be read
    hospital_email: bool  # signed in from a mailbox at this hospital
    approve: bool


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).replace("臺", "台")


def hospital_of(name: str) -> Hospital | None:
    norm = normalize(name)
    if "分院" in norm:
        return None
    found = {h for h in HOSPITALS if any(alias in norm for alias in h.names)}
    return found.pop() if len(found) == 1 else None


def mail_at(email: str | None, hospital: Hospital | None) -> bool:
    if not email or hospital is None or email.count("@") != 1:
        return False
    domain = email.rsplit("@", 1)[1].lower().rstrip(".")
    return any(domain == d or domain.endswith("." + d) for d in hospital.domains)


def parse_roster(page: str) -> Roster:
    """Doctors on the map page. A page without any is an error, so a redesign never reads as "not listed"."""
    roster: Roster = []
    for block in page.split('<div class="td-box">')[1:]:
        name = re.search(r'data-mtit="姓名/性別">\s*<img[^>]*\balt="([^"]+)"', block)
        posts = re.findall(r"<li>([^<|]+)\|[^<]*</li>", block)
        if name and posts:
            roster.append((normalize(html.unescape(name[1])), tuple(html.unescape(p).strip() for p in posts)))
    if not roster:
        raise ValueError("no doctors found on the roster page")
    return roster


def listed(roster: Roster, real_name: str, hospital: str) -> bool:
    """The name is on the map at the same hospital: the same HOSPITALS entry, or one name containing the other."""
    name, mine, entry = normalize(real_name), normalize(hospital), hospital_of(hospital)
    for doctor, posts in roster:
        if doctor != name:
            continue
        for post in map(normalize, posts):
            if post in mine or mine in post or (entry is not None and hospital_of(post) is entry):
                return True
    return False


def check(roster: Roster | None, real_name: str, hospital: str, proven_email: str | None) -> Check:
    entry = hospital_of(hospital)
    email = mail_at(proven_email, entry)
    if roster is None:
        return Check(None, email, False)
    # Approval needs the strict match: the posting maps to the very HOSPITALS entry whose domain the mail came from.
    strict = entry is not None and any(
        doctor == normalize(real_name) and any(hospital_of(post) is entry for post in posts) for doctor, posts in roster
    )
    return Check(listed(roster, real_name, hospital), email, strict and email)


class RosterSource:
    """The map page, fetched at most every CACHE_SECONDS; None when it cannot be read or parsed."""

    def __init__(self, fetch: Callable[[], str]) -> None:
        self._fetch = fetch
        self._cached: tuple[float, Roster] | None = None

    def get(self) -> Roster | None:
        if self._cached and time.monotonic() - self._cached[0] < CACHE_SECONDS:
            return self._cached[1]
        try:
            roster = parse_roster(self._fetch())
        except (OSError, ValueError, requests.RequestException):
            return None
        self._cached = (time.monotonic(), roster)
        return roster


def fetch_roster(url: str = ROSTER_URL) -> str:
    response = requests.get(url, timeout=8, headers={"User-Agent": "GutHub roster check"})
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text
