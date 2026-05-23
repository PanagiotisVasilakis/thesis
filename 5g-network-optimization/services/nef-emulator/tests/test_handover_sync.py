"""Tests for canonical handover orchestration symbols."""



def test_handover_engine_exposes_canonical_api():
    from backend.app.app.handover.engine import HandoverEngine

    assert hasattr(HandoverEngine, "evaluate_and_apply_handover")
