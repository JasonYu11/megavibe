from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_web_ui_exposes_telegram_feature_forms() -> None:
    html = (ROOT / "app/dashboard/static/index.html").read_text(encoding="utf-8")
    script = (ROOT / "app/dashboard/static/app.js").read_text(encoding="utf-8")

    for form_id in [
        "market-form",
        "limit-form",
        "quote-form",
        "order-command-form",
        "copy-command-form",
        "command-form",
    ]:
        assert f'id="{form_id}"' in html

    assert 'id="command-input-mode"' in html
    assert "标准 / 自然语言" in html
    assert 'class="manual-tool-pages"' in html
    assert 'data-tool-panel="market"' in html
    assert 'data-tool-panel-page="market"' in html
    assert 'id="nl-command-window"' not in html
    assert 'id="nl-command-form"' not in html

    for command in [
        "/buy",
        "/sell",
        "/limit_buy",
        "/limit_sell",
        "/quote",
        "/order",
        "/copy_set",
    ]:
        assert command in script

    assert "data-callback" in script
    assert "/api/callbacks" in script
    assert "/api/nl-commands/parse" in script
    assert "function isStandardCommand(text)" in script
    assert "function updateCommandInputMode()" in script
    assert "function showToolPanel(name)" in script
    assert "async function parseNaturalLanguageCommand(text)" in script
    assert "function renderTradeMessageCard(text" in script
    assert "function parseTradeMessage(text)" in script
    assert "function isLocalTradeCardDemo()" in script
    assert "trade-card" in script
    assert "function oklinkTxUrl(txHash)" in script
    assert "https://www.oklink.com/base/tx/" in script
    assert "https://www.oklink.com/base/address/" in script
    assert 'target="_blank" rel="noopener noreferrer"' in script
    assert "explorerLink(order.last_tx_hash" in script
    assert "explorerLink(event.tx_hash" in script
    assert "sendParsedNlCommand(command)" in script
    assert "await sendCommand(command);" in script
    assert "data-nl-send" in script
    assert ">是</button>" in script
    assert ">否</button>" in script
    assert "发送到对话" not in script
    assert "放入手动输入" not in script
    assert "data-nl-edit" not in script
    assert "target.dataset.nlDismiss" in script
