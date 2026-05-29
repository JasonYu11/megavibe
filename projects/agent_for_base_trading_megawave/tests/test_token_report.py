from __future__ import annotations

from app.data.token_report import TokenReportService


class FakeDebankClient:
    def get_token_info(self, token_address: str, chain_id: str = "base") -> dict:
        return {"id": token_address, "symbol": "TOKEN", "name": "Token", "price": "1.23"}

    def get_top_holders(self, token_address: str, chain_id: str = "base", limit: int = 10) -> list:
        return [["0xholder", 100]]


def test_token_report_covers_info_price_holders_and_message() -> None:
    report = TokenReportService(FakeDebankClient()).build("0x0000000000000000000000000000000000000001")

    assert report.token_info["symbol"] == "TOKEN"
    assert report.price == "1.23"
    assert report.top_holders == [["0xholder", 100]]
    assert "Top holders: 1" in report.format_telegram_message()

