"""Testes do parser de cookies: formatos, filtro de dominio, limites, dedupe."""

import json

import pytest

from app.services.cookies import (
    CookieImportError,
    MAX_DUMP_BYTES,
    has_auth_token,
    parse_cookie_dump,
)

NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    "#HttpOnly_.x.com\tTRUE\t/\tTRUE\t1777777777\tauth_token\tABC123\n"
    ".x.com\tTRUE\t/\tTRUE\t1777777777\tct0\tDEF456\n"
    ".google.com\tTRUE\t/\tTRUE\t1777777777\tNID\tshould-drop\n"
)


def test_netscape_keeps_only_x_and_normalizes() -> None:
    state = parse_cookie_dump(NETSCAPE)
    assert [c["name"] for c in state["cookies"]] == ["auth_token", "ct0"]
    auth = state["cookies"][0]
    assert auth["domain"] == ".x.com"
    assert auth["httpOnly"] is True
    assert auth["secure"] is True
    assert auth["sameSite"] == "None"  # cookie seguro sem sameSite informado
    assert auth["expires"] == 1777777777.0
    assert has_auth_token(state)


def test_netscape_session_cookie_expires_minus_one() -> None:
    dump = ".x.com\tTRUE\t/\tFALSE\t0\tguest_id\tv1\n"
    state = parse_cookie_dump(dump)
    assert state["cookies"][0]["expires"] == -1
    assert state["cookies"][0]["sameSite"] == "Lax"  # nao seguro -> Lax


def test_json_list_mixed_dialects() -> None:
    arr = json.dumps(
        [
            {"name": "auth_token", "value": "XYZ", "domain": ".x.com", "path": "/",
             "expirationDate": 1785000000.0, "hostOnly": False, "httpOnly": True,
             "secure": True, "sameSite": "no_restriction"},
            {"name": "guest_id", "value": "v1", "domain": "twitter.com", "path": "/",
             "expires": -1, "httpOnly": False, "secure": False},
            {"name": "malware", "value": "x", "domain": "evil.com", "path": "/"},
        ]
    )
    state = parse_cookie_dump(arr)
    assert [c["name"] for c in state["cookies"]] == ["auth_token", "guest_id"]
    assert state["cookies"][0]["sameSite"] == "None"
    assert state["cookies"][0]["expires"] == 1785000000.0
    assert state["cookies"][1]["sameSite"] == "Lax"
    assert state["cookies"][1]["expires"] == -1


def test_playwright_storage_state_filters_origins() -> None:
    state = json.dumps(
        {
            "cookies": [{"name": "auth_token", "value": "Q", "domain": ".x.com",
                         "path": "/", "expires": -1.0, "httpOnly": True,
                         "secure": True, "sameSite": "None"}],
            "origins": [
                {"origin": "https://x.com", "localStorage": [{"name": "a", "value": "1"}]},
                {"origin": "https://attacker.net", "localStorage": [{"name": "b", "value": "2"}]},
            ],
        }
    )
    result = parse_cookie_dump(state)
    assert len(result["cookies"]) == 1
    assert [o["origin"] for o in result["origins"]] == ["https://x.com"]


def test_single_cookie_json_object() -> None:
    single = json.dumps({"name": "auth_token", "value": "solo", "domain": ".x.com",
                         "path": "/", "expires": -1, "secure": True})
    state = parse_cookie_dump(single)
    assert state["cookies"][0]["value"] == "solo"


def test_dedupe_keeps_last_occurrence() -> None:
    dup = (
        ".x.com\tTRUE\t/\tTRUE\t1777777777\tauth_token\tOLD\n"
        ".x.com\tTRUE\t/\tTRUE\t1777777777\tauth_token\tNEW\n"
    )
    state = parse_cookie_dump(dup)
    assert len(state["cookies"]) == 1
    assert state["cookies"][0]["value"] == "NEW"


@pytest.mark.parametrize(
    "dump",
    [
        "",
        "   \n  ",
        "# so comentario\n",
        ".google.com\tTRUE\t/\tTRUE\t0\tNID\tx",
        ".evilx.com\tTRUE\t/\tTRUE\t1777777777\tk\tv",  # sufixo parcial NAO passa
    ],
)
def test_invalid_dumps_raise(dump: str) -> None:
    with pytest.raises(CookieImportError):
        parse_cookie_dump(dump)


def test_big_dump_passes_when_has_x_cookies() -> None:
    line = ".random-site-%d.com\tTRUE\t/\tTRUE\t1777777777\tc\tv\n"
    big = "".join(line % i for i in range(6000))
    big += ".x.com\tTRUE\t/\tTRUE\t1777777777\tauth_token\tTOKEN\n"
    assert len(big.encode()) > 256 * 1024  # exercita o caso real do export "all cookies"
    state = parse_cookie_dump(big)
    assert [c["name"] for c in state["cookies"]] == ["auth_token"]


def test_oversize_dump_rejected() -> None:
    with pytest.raises(CookieImportError, match="muito grande"):
        parse_cookie_dump("x" * (MAX_DUMP_BYTES + 1))


def test_has_auth_token() -> None:
    assert has_auth_token({"cookies": [{"name": "auth_token", "value": "x"}]})
    assert not has_auth_token({"cookies": [{"name": "auth_token", "value": ""}]})
    assert not has_auth_token({"cookies": [{"name": "ct0", "value": "x"}]})


def test_threads_platform_keeps_only_threads_domain() -> None:
    dump = (
        ".threads.com\tTRUE\t/\tTRUE\t1803911624\tsessionid\tABC123\n"
        ".x.com\tTRUE\t/\tTRUE\t1777777777\tauth_token\tshould-drop\n"
    )
    state = parse_cookie_dump(dump, platform="threads")
    assert [c["name"] for c in state["cookies"]] == ["sessionid"]
    assert has_auth_token(state, platform="threads")
    assert not has_auth_token(state, platform="x")


def test_threads_platform_rejects_x_only_dump() -> None:
    with pytest.raises(CookieImportError):
        parse_cookie_dump(".x.com\tTRUE\t/\tTRUE\t1777777777\tauth_token\tABC\n", platform="threads")


def test_unknown_platform_raises() -> None:
    with pytest.raises(CookieImportError):
        parse_cookie_dump(".x.com\tTRUE\t/\tTRUE\t1777777777\tauth_token\tABC\n", platform="bluesky")
