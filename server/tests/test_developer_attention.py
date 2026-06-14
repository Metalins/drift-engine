"""Developer API `attention` shape — gh-81.

`GET /v1/agents/{id}` returns `attention`: the warning-severity factors a
customer should look at. gh-81 turns each entry from a bare string into an
object carrying the factor `code` and a `learn_more` triplet (what it means /
is it a real problem / next step), so an integrator polling the API gets the
same context the dashboard shows. These unit-test `_attention` directly with
synthetic trust blocks — no DB or HTTP needed.
"""
from app.api.developer import _attention


def _trust_with(*, crypto=None, behavioral=None):
    return {
        "cryptographic": {"factors": crypto or []},
        "behavioral": {"factors": behavioral or []},
    }


def test_attention_items_are_objects_with_code_and_learn_more():
    trust = _trust_with(
        crypto=[
            {
                "severity": "warning",
                "code": "probes_failing",
                "message": "Recent memory checks are failing.",
                "learn_more": {
                    "what": "…",
                    "self_resolving": "…",
                    "action": "…",
                },
            }
        ]
    )
    items = _attention(trust)
    assert len(items) == 1
    item = items[0]
    assert item["message"] == "Recent memory checks are failing."
    assert item["code"] == "probes_failing"
    assert set(item["learn_more"]) == {"what", "self_resolving", "action"}


def test_attention_only_includes_warning_factors():
    """Good / info factors are not 'attention' — they don't show up."""
    trust = _trust_with(
        crypto=[
            {"severity": "good", "code": "probes_healthy", "message": "ok"},
        ],
        behavioral=[
            {"severity": "info", "code": "behavioral_calibrating", "message": "…"},
            {"severity": "warning", "code": "behavioral_drift", "message": "drifted"},
        ],
    )
    items = _attention(trust)
    assert [i["code"] for i in items] == ["behavioral_drift"]


def test_attention_learn_more_is_null_when_absent():
    """A warning factor that somehow lacks guidance still produces a valid
    item — `learn_more` is null, never a KeyError."""
    trust = _trust_with(
        behavioral=[
            {"severity": "warning", "code": "behavioral_drift", "message": "drifted"},
        ]
    )
    items = _attention(trust)
    assert items[0]["learn_more"] is None


def test_attention_empty_and_none_trust():
    assert _attention(None) == []
    assert _attention({}) == []
    assert _attention(_trust_with()) == []
