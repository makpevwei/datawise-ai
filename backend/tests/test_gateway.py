"""LLMGateway: retry (same provider, transient only) -> fallback (next
configured provider) -> honest final failure. Every test here uses
FakeRaisingProvider -- never a real provider SDK."""

from app.ai.errors import PermanentLLMError, TransientLLMError
from app.ai.gateway import LLMGateway
from app.ai.types import ConversationTurn, LLMTurn
from tests.fakes import FakeRaisingProvider


def _send(gateway: LLMGateway) -> LLMTurn:
    return gateway.send("system", [ConversationTurn(role="user", text="hi")], [])


def test_primary_success_no_retry_records_metadata():
    primary = FakeRaisingProvider("openai", to_raise=[])
    gateway = LLMGateway(providers=[primary], max_retries=3)

    turn = _send(gateway)

    assert turn.stop_reason == "end_turn"
    assert primary.call_count == 1
    assert turn.metadata.provider == "openai"
    assert turn.metadata.model == "openai-model"
    assert turn.metadata.fallback_used is False
    assert turn.metadata.attempt_count == 1


def test_retries_transient_failure_then_succeeds_same_provider():
    primary = FakeRaisingProvider(
        "openai",
        to_raise=[TransientLLMError("timeout"), TransientLLMError("timeout again")],
    )
    gateway = LLMGateway(providers=[primary], max_retries=3)

    turn = _send(gateway)

    assert turn.stop_reason == "end_turn"
    assert primary.call_count == 3
    assert turn.metadata.provider == "openai"
    assert turn.metadata.fallback_used is False
    assert turn.metadata.attempt_count == 3


def test_exhausting_retries_falls_back_to_second_provider():
    primary = FakeRaisingProvider("openai", to_raise=[TransientLLMError("down")] * 10)
    secondary = FakeRaisingProvider("gemini", to_raise=[])
    gateway = LLMGateway(providers=[primary, secondary], max_retries=2)

    turn = _send(gateway)

    assert turn.stop_reason == "end_turn"
    assert primary.call_count == 3  # 1 initial + 2 retries, all transient
    assert secondary.call_count == 1
    assert turn.metadata.provider == "gemini"
    assert turn.metadata.fallback_used is True
    assert turn.metadata.attempt_count == 4


def test_permanent_error_skips_retries_and_falls_back_immediately():
    primary = FakeRaisingProvider("openai", to_raise=[PermanentLLMError("bad api key")])
    secondary = FakeRaisingProvider("gemini", to_raise=[])
    gateway = LLMGateway(providers=[primary, secondary], max_retries=3)

    turn = _send(gateway)

    assert turn.stop_reason == "end_turn"
    assert primary.call_count == 1  # never retried
    assert secondary.call_count == 1
    assert turn.metadata.provider == "gemini"
    assert turn.metadata.fallback_used is True


def test_fallback_reaches_third_provider_when_first_two_fail():
    primary = FakeRaisingProvider("openai", to_raise=[PermanentLLMError("bad key")])
    secondary = FakeRaisingProvider("gemini", to_raise=[TransientLLMError("down")])
    tertiary = FakeRaisingProvider("groq", to_raise=[])
    gateway = LLMGateway(providers=[primary, secondary, tertiary], max_retries=0)

    turn = _send(gateway)

    assert turn.stop_reason == "end_turn"
    assert turn.metadata.provider == "groq"
    assert turn.metadata.fallback_used is True


def test_all_providers_failing_returns_honest_final_failure():
    primary = FakeRaisingProvider("openai", to_raise=[PermanentLLMError("bad key")])
    secondary = FakeRaisingProvider("gemini", to_raise=[TransientLLMError("down")])
    gateway = LLMGateway(providers=[primary, secondary], max_retries=0)

    turn = _send(gateway)

    assert turn.stop_reason == "error"
    assert "failed" in turn.text.lower()
    assert turn.metadata is not None
    assert turn.metadata.fallback_used is True


def test_max_retries_bounds_total_attempts_with_no_fallback_configured():
    primary = FakeRaisingProvider("openai", to_raise=[TransientLLMError("down")] * 100)
    gateway = LLMGateway(providers=[primary], max_retries=3)

    turn = _send(gateway)

    assert turn.stop_reason == "error"
    assert primary.call_count == 4  # 1 initial + 3 retries, then honest failure
    assert turn.metadata.attempt_count == 4


def test_credential_leakage_prevention_redacts_secret_in_final_failure_message():
    leaking_error = TransientLLMError(
        "connection failed for key sk-testFAKESECRETVALUE1234567890ABCDEFGH"
    )
    primary = FakeRaisingProvider("openai", to_raise=[leaking_error])
    gateway = LLMGateway(providers=[primary], max_retries=0)

    turn = _send(gateway)

    assert turn.stop_reason == "error"
    assert "sk-testFAKESECRETVALUE1234567890ABCDEFGH" not in turn.text
    assert "[REDACTED]" in turn.text
