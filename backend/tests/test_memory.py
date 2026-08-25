from app.agent.memory import MAX_TURNS_REMEMBERED, ConversationMemory


def test_empty_session_has_no_prompt_context():
    memory = ConversationMemory()
    assert memory.format_for_prompt("s1") is None


def test_remembers_prior_question_and_answer():
    memory = ConversationMemory()
    memory.append("s1", "Show revenue by region.", "North led with 34% of revenue.")
    context = memory.format_for_prompt("s1")
    assert "Show revenue by region." in context
    assert "North led with 34%" in context


def test_sessions_are_isolated():
    memory = ConversationMemory()
    memory.append("s1", "Question in session 1", "answer 1")
    memory.append("s2", "Question in session 2", "answer 2")
    assert "session 1" in memory.format_for_prompt("s1")
    assert "session 1" not in memory.format_for_prompt("s2")


def test_caps_remembered_turns():
    memory = ConversationMemory()
    for i in range(MAX_TURNS_REMEMBERED + 5):
        memory.append("s1", f"Question {i}", f"Answer {i}")
    history = memory.get_history("s1")
    assert len(history) == MAX_TURNS_REMEMBERED
    # oldest turns are dropped, most recent kept
    assert history[-1].question == f"Question {MAX_TURNS_REMEMBERED + 4}"
    assert history[0].question == f"Question {5}"
