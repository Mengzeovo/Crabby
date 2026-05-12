from __future__ import annotations

from attachment_store import AttachmentStore
from config import settings
from memory import Session
from skills.models import Skill
from skills.registry import SkillRegistry
from user_turn import prepare_user_turn


ONE_BY_ONE_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/w8AAgMBgJ8LvwAAAABJRU5ErkJggg=="
)


def test_prepare_user_turn_forces_skill_and_reads_vault_file(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "notes file.md"
    note.write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")

    monkeypatch.setattr(settings, "vault_path", vault)

    registry = SkillRegistry()
    registry.register(Skill(name="review", description="review notes"))
    store = AttachmentStore(tmp_path / "attachments")

    prepared = prepare_user_turn(
        content='/review @"notes file.md"#L2-3 explain this',
        pasted_contents=[],
        skill_registry=registry,
        attachment_store=store,
    )

    assert prepared.command == {"name": "review", "args": '@"notes file.md"#L2-3 explain this'}
    assert [skill.name for skill in prepared.active_skills] == ["review"]
    assert prepared.attachments[0]["type"] == "vault_file"
    assert prepared.attachments[0]["path"] == "notes file.md"
    assert prepared.attachments[0]["content"] == "line 2\nline 3"
    assert prepared.text == '/review @"notes file.md"#L2-3 explain this'


def test_prepare_user_turn_allows_inline_command_and_mentions(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "nested note.md"
    note.write_text("alpha\nbeta\n", encoding="utf-8")

    monkeypatch.setattr(settings, "vault_path", vault)

    registry = SkillRegistry()
    registry.register(Skill(name="review", description="review notes"))
    store = AttachmentStore(tmp_path / "attachments")

    prepared = prepare_user_turn(
        content='请/review看下@"nested note.md"',
        pasted_contents=[],
        skill_registry=registry,
        attachment_store=store,
    )

    assert prepared.command == {"name": "review", "args": '请看下@"nested note.md"'}
    assert [skill.name for skill in prepared.active_skills] == ["review"]
    assert prepared.attachments[0]["path"] == "nested note.md"
    assert prepared.model_text == '请看下@"nested note.md"'


def test_session_get_messages_rebuilds_image_blocks_without_storing_base64(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "vault_path", tmp_path)
    monkeypatch.setattr(settings, "llm_supports_vision", True)

    store = AttachmentStore(tmp_path / "attachments")
    prepared = prepare_user_turn(
        content="Please inspect this [Image #1]",
        pasted_contents=[
            {
                "id": 1,
                "type": "image",
                "data": ONE_BY_ONE_PNG,
                "media_type": "image/png",
                "filename": "clip.png",
                "width": 1,
                "height": 1,
            }
        ],
        skill_registry=None,
        attachment_store=store,
    )

    session = Session(id="images")
    message_id = session.add_user_prepared_turn(prepared)
    assert message_id.startswith("m_")

    stored_message = session.messages[-1]
    assert stored_message["message_id"] == message_id
    assert "content" not in stored_message
    assert stored_message["attachments"][0]["type"] == "image"
    assert ONE_BY_ONE_PNG not in str(stored_message)

    messages = session.get_messages(store)
    assert isinstance(messages[0]["content"], list)
    assert messages[0]["content"][0]["type"] == "image"
    assert messages[0]["content"][-1]["text"] == "Please inspect this"


def test_prepare_user_turn_accepts_image_only_payloads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "vault_path", tmp_path)
    monkeypatch.setattr(settings, "llm_supports_vision", True)

    store = AttachmentStore(tmp_path / "attachments")
    prepared = prepare_user_turn(
        content="",
        pasted_contents=[
            {
                "id": 7,
                "type": "image",
                "data": ONE_BY_ONE_PNG,
                "media_type": "image/png",
                "filename": "image-only.png",
            }
        ],
        skill_registry=None,
        attachment_store=store,
    )

    assert prepared.text == ""
    assert prepared.attachments[0]["type"] == "image"
    assert prepared.model_blocks[0]["type"] == "image"
