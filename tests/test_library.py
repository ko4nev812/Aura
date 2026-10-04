"""Фаза 1: схема БД и Library Manager (ТЗ §3.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text

from aura.db.database import Database
from aura.db.models import AppRule, BanditArm, Feedback, Pack, PlayEvent, Track, TrackAnalysis


def test_schema_tables_and_pragmas(tmp_path):
    db = Database(tmp_path / "aura.db")
    db.create_schema()
    with db.session() as session:
        names = {row[0] for row in session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        journal = session.execute(text("PRAGMA journal_mode")).scalar()
        foreign = session.execute(text("PRAGMA foreign_keys")).scalar()
    assert {
        "packs",
        "tracks",
        "track_analysis",
        "app_rules",
        "feedback",
        "play_events",
        "bandit_arms",
        "settings",
    } <= names
    assert str(journal).lower() == "wal"
    assert int(foreign) == 1
    db.close()


def test_pack_and_track_roundtrip(tmp_path):
    db = Database(tmp_path / "aura.db")
    db.create_schema()
    with db.session() as session:
        pack = Pack(name="Lo-Fi", source="local")
        session.add(pack)
        session.flush()
        track = Track(
            pack_id=pack.id,
            title="Rain",
            artist="AurA",
            file_path="C:/x/rain.mp3",
            duration_sec=182,
            format="mp3",
        )
        session.add(track)
        session.flush()
        session.add(TrackAnalysis(track_id=track.id, bpm=72.5, energy=0.3, mood_tags=["calm"]))
        first_pack_id, first_track_id = pack.id, track.id

    with db.new_session() as session:
        loaded = session.get(Track, first_track_id)
        assert loaded is not None
        assert loaded.pack.name == "Lo-Fi"
        assert loaded.analysis is not None
        assert loaded.analysis.mood_tags == ["calm"]
        assert loaded.analysis.bpm == pytest.approx(72.5)
        assert loaded.is_playable is True

    # тумблер пака не трогает треки, включённые вручную
    with db.session() as session:
        session.get(Pack, first_pack_id).enabled = False
    with db.new_session() as session:
        pack = session.get(Pack, first_pack_id)
        assert pack.enabled is False
        assert pack.tracks[0].enabled is True
    db.close()


def test_pack_delete_cascades_to_tracks_and_children(tmp_path):
    db = Database(tmp_path / "aura.db")
    db.create_schema()
    with db.session() as session:
        pack = Pack(name="Trash")
        session.add(pack)
        session.flush()
        track = Track(pack_id=pack.id, title="T", file_path="C:/t.mp3")
        session.add(track)
        session.flush()
        session.add_all(
            [
                Feedback(track_id=track.id, rating=1),
                PlayEvent(track_id=track.id),
                BanditArm(track_id=track.id),
                TrackAnalysis(track_id=track.id, bpm=100.0),
            ]
        )
        pack_id = pack.id

    with db.session() as session:
        session.delete(session.get(Pack, pack_id))

    with db.new_session() as session:
        for model in (Track, Feedback, PlayEvent, BanditArm, TrackAnalysis, AppRule):
            assert session.scalars(select(model)).all() == []
    db.close()


def test_renames_and_validation(service):
    pack = service.library.create_pack("  Work  ")
    assert service.library.create_pack("work").id == pack.id  # регистронезависимый дедуп
    with pytest.raises(ValueError):
        service.library.create_pack("   ")
    renamed = service.library.rename_pack(pack.id, "Focus")
    assert renamed.name == "Focus"
    assert service.library.find_pack_by_name("FOCUS").id == pack.id


def test_import_folder_and_track_ops(service, music_dir, paths):
    result = service.library.import_directory(music_dir)
    assert result.scanned == 3
    assert result.imported == 3
    assert (result.skipped_existing, result.skipped_unreadable) == (0, 0)

    pack = service.library.find_pack_by_name("music")
    assert pack is not None and pack.track_count == 3
    titles = {track.title for track in pack.tracks}
    assert "Slow Motion" in titles  # "Artist - Title" разбирается из имени файла
    assert all(track.exists for track in pack.tracks)

    again = service.library.import_directory(music_dir, pack_name="music")
    assert again.imported == 0 and again.skipped_existing == 3

    first = pack.tracks[0]
    service.library.set_track_enabled(first.id, False)
    assert service.library.get_track(first.id).enabled is False
    assert first.id not in {t.id for t in service.library.list_tracks(enabled_only=True)}

    other = service.library.create_pack("Other")
    moved = service.library.move_track(first.id, other.id)
    assert moved.pack_id == other.id
    assert service.library.get_pack(other.id).track_count == 1

    assert service.library.delete_track(first.id) is True
    assert service.library.get_track(first.id) is None


def test_copy_mode_places_files_in_library(service, music_dir, paths):
    result = service.library.import_directory(music_dir, pack_name="Copies", copy_files=True)
    assert result.imported == 3
    pack = service.library.find_pack_by_name("Copies")
    for track in pack.tracks:
        stored = Path(track.file_path)
        assert stored.is_relative_to(paths.library.resolve())
        assert stored.exists()


def test_delete_pack_keeps_files_by_default(service, music_dir):
    service.library.import_directory(music_dir, pack_name="Temp")
    pack = service.library.find_pack_by_name("Temp")
    paths_before = [Path(track.file_path) for track in pack.tracks]
    assert service.library.delete_pack(pack.id) == 3
    assert all(path.exists() for path in paths_before)
    assert service.library.get_pack(pack.id) is None


def test_missing_files_are_disabled(service, music_dir):
    service.library.import_directory(music_dir)
    track = service.library.list_tracks()[0]
    file_path = Path(track.file_path)
    file_path.unlink()
    missing = service.library.mark_missing_files()
    assert str(file_path) in missing
    assert service.library.get_track(track.id).exists is False
    assert service.library.get_track(track.id).enabled is False


def test_feedback_and_play_events(service, music_dir):
    service.library.import_directory(music_dir)
    track = service.library.list_tracks()[0]
    assert service.library.record_feedback(track.id, 1, context={"time_of_day": "day"}) is not None
    assert service.library.record_feedback(track.id, -1) is not None
    assert service.library.latest_feedback(track.id) == -1
    totals = service.library.feedback_totals()
    assert totals["likes"] == 1 and totals["dislikes"] == 1

    with pytest.raises(ValueError):
        service.library.record_feedback(track.id, 5)

    event_id = service.library.record_play(track.id, "session-1", None)
    assert event_id is not None
    assert service.library.record_play("missing-id") is None

    service.library.import_directory(music_dir, pack_name="Ambient Only")
    ambient_pack = service.library.find_pack_by_name("Ambient Only")
    service.library.set_pack_enabled(ambient_pack.id, True)
    stats = service.library.stats()
    assert stats["packs"] >= 2 and stats["tracks"] >= 3


def test_app_rules_crud(service):
    rule = service.library.add_rule("chrome.exe", title_pattern=".*YouTube.*", mode="pause", priority=10)
    assert rule.mode == "pause"
    assert service.library.add_rule("ZOOM.exe", mode="duck", duck_level=0.3).process_name == "zoom.exe"
    with pytest.raises(ValueError):
        service.library.add_rule("")
    with pytest.raises(ValueError):
        service.library.add_rule("x.exe", mode="nonsense")

    rules = service.library.list_rules()
    assert [r.process_name for r in rules] == ["chrome.exe", "zoom.exe"]  # приоритет 10 выше приоритета 0
    updated = service.library.update_rule(rules[0].id, enabled=False, priority=50)
    assert updated.enabled is False and updated.priority == 50
    with pytest.raises(ValueError):
        service.library.update_rule(rules[-1].id, nope=1)
    assert service.library.delete_rule(rules[0].id) is True
    assert len(service.library.list_rules()) == 1


def test_tracks_needing_analysis(service, music_dir):
    service.library.import_directory(music_dir)
    pending = service.library.tracks_needing_analysis()
    assert len(pending) == 3
