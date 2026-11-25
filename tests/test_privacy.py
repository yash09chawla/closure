"""The outbound guard is the safety net for 'no candidate data to OpenAI'. Synthetic identities only."""
import asyncio

import pytest

from app import llm, privacy

SAFE = [
    "Find the passing criteria for B.E. Civil Engineering (full-time, 4 years, regulation 2017) at Anna University.",
    "Academic year 2021 - 2025, regulation 2017 (CBCS), affiliated college",
    "Anna University, Chennai 600025 — official website",
    'What is the official website of the Indian higher-education institution "Example Institute of Technology"?',
]
UNSAFE_GENERIC = [
    "contact test.person@example.com",
    "register no 123456789012",
    "born 04-JAN-2001",
    "roll AB12345678CD",
    "phone +91 9876543210",
]


@pytest.mark.parametrize("text", SAFE)
def test_general_programme_queries_pass(text):
    assert privacy.problems(text) == []


@pytest.mark.parametrize("text", UNSAFE_GENERIC)
def test_generic_personal_patterns_blocked(text):
    assert privacy.problems(text)


def test_case_identifiers_block_name_and_number_in_any_format():
    with privacy.case_identifiers(["RAVI KUMAR SHARMA", "56789/RG"]):
        assert "candidate name" in privacy.problems("passing criteria for Ravi Kumar at X University")
        assert privacy.problems("register 56789 at X University")
        assert privacy.problems("X University B.Tech 2019") == []
    # outside the block nothing case-specific is remembered
    assert privacy.problems("passing criteria for Ravi Kumar at X University") == []


def test_identifiers_added_later_reach_tasks_started_earlier():
    async def main():
        with privacy.case_identifiers(["RAVI KUMAR"]):
            started = asyncio.Event()
            go = asyncio.Event()

            async def research_task():
                started.set()
                await go.wait()
                return privacy.problems("register 4455667 B.Tech")

            t = asyncio.create_task(research_task())
            await started.wait()
            privacy.add_identifiers(["4455667"])   # discovered on the degree after the task started
            go.set()
            return await t
    assert "candidate identifier (number)" in asyncio.run(main())


def test_llm_refuses_before_any_network_call(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)

    def boom():
        raise AssertionError("the OpenAI client must not be created for a blocked prompt")
    monkeypatch.setattr(llm, "client", boom)
    with pytest.raises(privacy.PrivacyViolation):
        llm.web_search_json("regulations for student test.person@example.com", ["example.ac.in"], "test")


def test_llm_has_no_document_or_image_entry_point():
    # documents are read locally; the OpenAI wrapper must not offer a way to send them
    assert not hasattr(llm, "extract_json")
    assert not hasattr(llm, "image_to_data_url")
