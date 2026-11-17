"""Automatic surgeon approval (H10 #168): reading the doctor map and matching name, hospital and mailbox.

The fixture keeps the map page's real markup with fictional people in it.
"""

from pathlib import Path

import pytest

from guthub_api.surgeon_roster import HOSPITALS, RosterSource, check, hospital_of, mail_at, parse_roster

PAGE = (Path(__file__).parent / "fixtures" / "crs_roster.html").read_text(encoding="utf-8")
ROSTER = parse_roster(PAGE)


def test_the_map_page_is_read_into_names_and_hospitals() -> None:
    assert ROSTER == [
        ("王大明", ("台北榮民總醫院",)),
        ("陳小華", ("嘉義長庚紀念醫院", "雲林長庚紀念醫院")),
    ]


def test_a_redesigned_page_is_an_error_not_an_empty_roster() -> None:
    with pytest.raises(ValueError, match="no doctors"):
        parse_roster("<html><body>醫師地圖</body></html>")


@pytest.mark.parametrize(
    ("typed", "label"),
    [
        ("臺北榮民總醫院", "臺北榮民總醫院"),
        ("台北榮總", "臺北榮民總醫院"),
        ("北榮 大腸直腸外科", "臺北榮民總醫院"),
        ("林口長庚紀念醫院", "長庚紀念醫院"),
        ("ＮＴＵＨ 台大醫院", "臺大醫院"),  # full-width letters fold
    ],
)
def test_hospital_names_are_recognised(typed: str, label: str) -> None:
    hospital = hospital_of(typed)
    assert hospital is not None and hospital.label == label


@pytest.mark.parametrize("typed", ["臺北榮民總醫院桃園分院", "某某診所", "台大醫院新竹分院"])
def test_branches_and_unknown_hospitals_are_left_to_the_maintainer(typed: str) -> None:
    assert hospital_of(typed) is None


def test_every_alias_picks_exactly_one_hospital() -> None:
    for hospital in HOSPITALS:
        for alias in hospital.names:
            assert hospital_of(alias) is hospital, alias


def test_mail_domains_match_exactly_or_as_a_subdomain() -> None:
    chang_gung = hospital_of("長庚")
    assert mail_at("dr@cgmh.org.tw", chang_gung)
    assert mail_at("dr@adm.CGMH.org.tw", chang_gung)
    assert not mail_at("dr@notcgmh.org.tw", chang_gung)
    assert not mail_at("dr@cgmh.org.tw.example.com", chang_gung)
    assert not mail_at("dr@gmail.com", chang_gung)
    assert not mail_at(None, chang_gung)
    assert not mail_at("dr@cgmh.org.tw", None)


def test_listed_with_a_hospital_mailbox_is_approved() -> None:
    verdict = check(ROSTER, "陳小華", "雲林長庚", "chen@cgmh.org.tw")
    assert verdict.listed and verdict.hospital_email and verdict.approve


@pytest.mark.parametrize(
    ("name", "hospital", "email", "listed", "hospital_email"),
    [
        ("陳小華", "雲林長庚", "chen@gmail.com", True, False),  # anyone can type a listed name
        ("陳小華", "雲林長庚", None, True, False),  # a password session proved no mailbox
        ("陳大華", "嘉義長庚", "chen@cgmh.org.tw", False, True),  # a colleague's mailbox, a name not on the map
        ("王大明", "林口長庚", "wang@cgmh.org.tw", False, True),  # listed, but at another hospital
        ("王大明", "台北榮總", "wang@cgmh.org.tw", True, False),  # mailbox of another hospital
    ],
)
def test_anything_short_of_both_waits_for_the_maintainer(
    name: str, hospital: str, email: str | None, listed: bool, hospital_email: bool
) -> None:
    verdict = check(ROSTER, name, hospital, email)
    assert (verdict.listed, verdict.hospital_email, verdict.approve) == (listed, hospital_email, False)


def test_an_unreadable_map_approves_nobody() -> None:
    verdict = check(None, "陳小華", "雲林長庚", "chen@cgmh.org.tw")
    assert verdict.listed is None and not verdict.approve


def test_the_source_caches_and_reports_failures_as_none() -> None:
    calls: list[int] = []

    def page() -> str:
        calls.append(1)
        return PAGE

    source = RosterSource(page)
    assert source.get() == ROSTER and source.get() == ROSTER and len(calls) == 1

    def down() -> str:
        raise OSError("timed out")

    assert RosterSource(down).get() is None
    assert RosterSource(lambda: "<html>改版</html>").get() is None
