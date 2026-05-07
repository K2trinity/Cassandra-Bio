from __future__ import annotations

from scripts import kline_preview_server


def test_preview_url_uses_localhost_for_all_interface_bind():
    assert (
        kline_preview_server.preview_url("0.0.0.0", 7917, "mrna")
        == "http://127.0.0.1:7917/kline/MRNA"
    )


def test_preview_url_can_show_formal_lan_address_for_all_interface_bind():
    assert (
        kline_preview_server.preview_url(
            "0.0.0.0",
            7897,
            "mrna",
            public_host="10.21.158.104",
        )
        == "http://10.21.158.104:7897/kline/MRNA"
    )


def test_parse_args_formal_profile_uses_formal_bind_port_and_public_host():
    args = kline_preview_server.parse_args(
        ["--formal", "--public-host", "10.21.158.104"]
    )

    assert args.host == "0.0.0.0"
    assert args.port == 7897
    assert args.public_host == "10.21.158.104"


def test_parse_args_defaults_to_stable_kline_preview_port():
    args = kline_preview_server.parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 7917
    assert args.ticker == "MRNA"
