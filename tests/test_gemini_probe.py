import json
import sys
from unittest.mock import Mock

from scripts import benchmark_gemini_translation as probe


def test_marker_merges_are_allowed_but_renumbering_is_rejected():
    source = "[[s0001]]\nFirst\n[[s0002]]\nSecond\n[[s0003]]\nThird"
    assert probe.marker_check(source, "[[s0001]]\nПервое и второе\n[[s0002]]\n"
                              "[[s0003]]\nТретье")["valid"]
    assert not probe.marker_check(source, "[[s0001]]\nВсе\n[[s0002]]\nТретье")["valid"]


def test_paid_probe_saves_cost_including_thinking_and_does_not_resend(monkeypatch, tmp_path):
    output = tmp_path / "probe"
    output.mkdir()
    samples = [{"chunk": f"{index}/2", "local_seconds": 90,
                "payload": {"messages": [{"content": "Translate"},
                                          {"content": "[[s0001]]\nHello"}]},
                "local_text": "[[s0001]]\nПривет"} for index in (1, 2)]
    (output / "samples.json").write_text(json.dumps(samples))
    monkeypatch.setenv("GEMINI_API_KEY", "private-test-key")
    monkeypatch.setattr(sys, "argv", ["probe", str(tmp_path), "--output", str(output),
                                     "--run", "--paid-project"])
    response = Mock(ok=True)
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "[[s0001]]\nПривет"}]},
                        "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 500,
                          "thoughtsTokenCount": 100},
    }
    post = Mock(return_value=response)
    monkeypatch.setattr(probe.requests, "post", post)
    probe.main()
    assert post.call_count == 2
    result = json.loads((output / "gemini-3.5-flash-lite-1.json").read_text())
    assert abs(result["estimated_usd"] - .0018) < 1e-9
    assert result["marker_check"]["valid"]
    assert "private-test-key" not in "".join(p.read_text() for p in output.iterdir())
    probe.main()
    assert post.call_count == 2
