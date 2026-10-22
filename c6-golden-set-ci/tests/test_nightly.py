from golden_ci import nightly


def test_the_judge_reply_is_parsed_strictly():
    assert nightly.parse('{"score": 3, "reason": "fine"}') == {"score": 3, "reason": "fine"}
    assert nightly.parse('Here you go: {"score": 2, "reason": "vague"}')["score"] == 2
    # Unescaped quotes inside the reason: not valid JSON, but the score is still clear.
    loose = nightly.parse('{"score": 2, "reason": "the unfilled "[ADDRESS]" placeholder"}')
    assert loose == {"score": 2, "reason": 'the unfilled "[ADDRESS]" placeholder'}
    # Anything unusable counts as a critical failure, so a broken judge can't hide a bad night.
    assert nightly.parse("I think it's good")["score"] == 1
    assert nightly.parse('{"score": 7}')["score"] == 1


async def test_drift_pulls_the_score_below_the_sla():
    answered = {"says": "Has order 2 shipped yet?", "blocked_by": "", "tools": ["get-order-status"],
                "reply": "Order 2 is shipped.", "at": "2026-10-22T00:00:00+00:00"}
    turned_down = {"says": "How much is left on my gift card?", "blocked_by": "guardrail", "tools": [],
                   "reply": "Sorry, I can't help with that. I can help with your orders, deliveries and returns.",
                   "at": "2026-10-22T00:00:00+00:00"}
    calm = nightly.summarize(await nightly.score([answered] * 10, sample=10, seed=1), sla=0.9)
    drifted = nightly.summarize(await nightly.score([answered] * 6 + [turned_down] * 4, sample=10, seed=1), sla=0.9)
    assert not calm["alert"] and calm["share_ready"] == 1
    assert drifted["alert"] and drifted["share_ready"] == 0.6
