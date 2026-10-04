"""Фаза 1: smoke-тесты интерфейса (главное окно, вкладки, трей, тема).

Проверяем связку сигналов, состояния виджетов и сохранение настроек; реальный
декодер специально не доигрываем до конца.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QItemSelectionModel, Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from aura.audio.engine import gain_from_percent
from aura.audio.state import PlayerState
from aura.config import save_settings
from aura.ui.main_window import SHORTCUTS, MainWindow
from aura.ui.tabs.library_tab import PACK_ID_ROLE, TRACK_ID_ROLE
from aura.ui.theme import QSS, badge_icon, orb_icon, transport_icon
from aura.ui.tray import TrayController
from aura.ui.widgets import PulseOrb, format_duration, format_long_duration, format_size


@pytest.fixture
def loaded_service(service, music_dir):  # noqa: ARG001
    service.import_directory(music_dir)
    return service


@pytest.fixture
def window(qapp, loaded_service) -> MainWindow:  # noqa: ARG001
    main = MainWindow(loaded_service)
    yield main
    main.service.playlist.stop()


class FakeTray:
    """Минимальная заглушка трея: нужен только notify + факт наличия."""

    def __init__(self) -> None:
        self.notes: list[tuple[str, str]] = []

    def notify(self, title: str, message: str, ms: int = 0) -> None:  # noqa: ARG002
        self.notes.append((title, message))


def test_theme_helpers_produce_icons():
    assert not orb_icon(48).isNull()
    assert not badge_icon("playing", 22).isNull()
    for kind in ("play", "pause", "next", "prev", "like", "dislike", "volume", "youtube", "spinner"):
        assert not transport_icon(kind, 24).isNull(), kind
    assert "QPushButton" in QSS and "#8b5cf6" in QSS


def test_format_helpers():
    assert format_duration(0) == "--:--"
    assert format_duration(65) == "1:05"
    assert format_duration(3725) == "1:02:05"
    assert format_long_duration(0) == "0 мин"
    assert format_long_duration(3725) == "1 ч 2 мин"
    assert format_size(1024) == "1.0 КБ"
    assert format_size(5 * 1024 * 1024) == "5.0 МБ"


def test_pulse_orb_state(qapp):  # noqa: ARG001
    orb = PulseOrb(80)
    orb.set_progress(2.0)
    orb.set_active(True)
    orb.set_active(True)
    assert orb._progress == 1.0
    assert orb.is_pulsing is True
    orb.set_active(False)
    assert orb.is_pulsing is False
    orb.deleteLater()


def test_main_window_has_five_tabs(window, loaded_service):
    assert window.tabs.count() == 5
    titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert titles == ["Сейчас играет", "Библиотека", "Правила", "Аналитика", "Настройки"]
    assert window.tabs.widget(0) is window.now_tab
    assert window.windowTitle() == "Aura"
    assert loaded_service.window is window
    assert window.centralWidget() is window.tabs


def test_now_playing_tab_is_empty_initially(window):
    tab = window.now_tab
    assert tab.title_label.text() == "Ничего не играет"
    assert tab.like_button.isEnabled() is False
    assert tab.dislike_button.isEnabled() is False
    assert tab.queue_label.text().startswith("—")
    assert tab.scheduler_badge.text().startswith("scheduler: random")
    assert tab.state_label.text() == PlayerState.IDLE.label


def test_now_playing_reflects_playback(window, loaded_service, qapp):
    tab = window.now_tab
    track = loaded_service.library.list_tracks()[0]
    assert loaded_service.playlist.play(track) is True
    qapp.processEvents()

    assert tab.title_label.text() == track.title
    assert tab.artist_label.text() == (track.artist or "неизвестный исполнитель")
    assert "пак: music" in tab.pack_label.text()
    assert tab.like_button.isEnabled() is True
    assert "фаза 2" in tab.analysis_label.text()
    assert window.windowTitle().startswith("Aura —")
    assert "Играем" in window.status_message.text()

    loaded_service.playlist.stop()
    qapp.processEvents()
    assert tab.title_label.text() == "Ничего не играет"
    assert window.windowTitle() == "Aura"


def test_like_and_dislike_persist(window, loaded_service, qapp):
    track = loaded_service.library.list_tracks()[0]
    loaded_service.playlist.play(track)
    qapp.processEvents()

    window.now_tab.rate(1)
    qapp.processEvents()
    assert loaded_service.library.latest_feedback(track.id) == 1
    assert window.now_tab.like_button.isChecked() is True
    assert window.now_tab.dislike_button.isChecked() is False

    window.now_tab.rate(-1)
    assert loaded_service.library.latest_feedback(track.id) == -1
    assert window.now_tab.like_button.isChecked() is False
    assert window.now_tab.dislike_button.isChecked() is True
    assert loaded_service.library.feedback_totals()["dislikes"] == 1


def test_library_tree_shows_packs_and_toggles(window, loaded_service, qapp):
    tab = window.library_tab
    assert tab.tree.topLevelItemCount() == 1
    pack_item = tab.tree.topLevelItem(0)
    assert pack_item.text(0) == "music"
    assert pack_item.childCount() == 3
    assert pack_item.checkState(0) == Qt.CheckState.Checked
    assert "Паков: 1" in tab.status.text()

    child = pack_item.child(0)
    child_id = str(child.data(0, TRACK_ID_ROLE))
    child.setCheckState(0, Qt.CheckState.Unchecked)
    qapp.processEvents()
    assert loaded_service.library.get_track(child_id).enabled is False
    assert tab._find_track(child_id).checkState(0) == Qt.CheckState.Unchecked

    refreshed = tab.tree.topLevelItem(0)
    pack_id = str(refreshed.data(0, PACK_ID_ROLE))
    refreshed.setCheckState(0, Qt.CheckState.Unchecked)
    qapp.processEvents()
    assert loaded_service.library.get_pack(pack_id).enabled is False
    assert tab.tree.topLevelItem(0).checkState(0) == Qt.CheckState.Unchecked
    assert "включено: 0" in tab.status.text()

    third = tab.tree.topLevelItem(0).child(2)
    assert third.text(3) != ""  # формат из ffprobe (реальный кодек, а не расширение)
    assert third.text(2) != ""  # длительность из ffprobe/эвристики


def test_library_search_filters_rows(window, loaded_service, qapp):  # noqa: ARG001
    tab = window.library_tab
    tab.search.setText("Slow")
    qapp.processEvents()
    pack_item = tab.tree.topLevelItem(0)
    assert pack_item.childCount() == 1
    assert "Slow Motion" in pack_item.child(0).text(0)
    assert "фильтру: 1" in tab.status.text()

    tab.search.setText("")
    qapp.processEvents()
    assert tab.tree.topLevelItem(0).childCount() == 3


def test_library_play_selection_uses_queue(window, loaded_service, qapp):  # noqa: ARG001
    tab = window.library_tab
    tracks = loaded_service.library.list_tracks()
    selector = tab.tree.selectionModel()
    for index in (0, 1):
        item = tab._find_track(tracks[index].id)
        assert item is not None
        selector.select(
            tab.tree.indexFromItem(item),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    tab.play_selection()
    qapp.processEvents()
    assert loaded_service.playlist.current is not None
    assert len(loaded_service.playlist.queued_tracks) == 1


def test_rules_tab_crud(window, loaded_service, qapp):  # noqa: ARG001
    tab = window.rules_tab
    assert tab.table.rowCount() == 0
    rule = loaded_service.library.add_rule("game.exe", mode="pause", priority=5)
    tab.reload()
    qapp.processEvents()

    assert tab.table.rowCount() == 1
    assert tab.table.item(0, 0).text() == "game.exe"
    assert "пауза" in tab.table.item(0, 2).text()
    assert tab.edit_button.isEnabled() is False

    tab.table.selectRow(0)
    assert tab.edit_button.isEnabled() and tab.remove_button.isEnabled()
    assert tab._selected_rule_id() == rule.id

    loaded_service.library.delete_rule(rule.id)
    tab.reload()
    assert tab.table.rowCount() == 0
    assert "Правил: 0" in tab.status.text()


def test_analytics_tab_counts(window, loaded_service, qapp):  # noqa: ARG001
    tab = window.analytics_tab
    tab.reload()
    qapp.processEvents()
    assert tab.card_widgets["packs"].text() == "1"
    assert tab.card_widgets["tracks"].text() == "3"
    assert tab.card_widgets["analyzed"].text() == "0"
    assert tab.card_widgets["playable"].text() == "3"
    assert tab.card_widgets["duration"].text() == format_long_duration(
        loaded_service.library.stats()["duration_sec"]
    )
    assert tab.card_widgets["likes"].text() == "0"
    assert tab.card_widgets["plays"].text() == "0"
    assert tab.top_table.rowCount() == 3  # топ строится по трекам библиотеки
    assert tab.empty_note.isHidden() is False


def test_settings_tab_save_roundtrip(window, loaded_service, qapp):
    tab = window.settings_tab
    tab.volume.setValue(33)
    tab.crossfade.setChecked(True)
    tab.crossfade_sec.setValue(3.5)
    tab.silence_max.setValue(45)
    tab.shuffle.setChecked(False)
    assert tab.dirty is True

    tab.save()
    qapp.processEvents()

    assert "Сохранено" in tab.status.text()
    settings = loaded_service.settings
    assert settings.volume == 33
    assert settings.crossfade_enabled is True
    assert settings.crossfade_sec == pytest.approx(3.5)
    assert settings.silence_max_sec == 45
    assert settings.shuffle is False
    assert loaded_service.engine.volume == pytest.approx(gain_from_percent(33))
    assert tab.dirty is False

    text = loaded_service.paths.config_file.read_text(encoding="utf-8")
    assert "volume: 33" in text and "crossfade_sec: 3.5" in text
    assert "scheduler_backend: random" in text

    tab.load_values()
    assert tab.volume.value() == 33
    assert tab.shuffle.isChecked() is False


def test_settings_tab_rejects_bad_silence(window, loaded_service, monkeypatch):
    tab = window.settings_tab
    tab.silence_min.setValue(90)
    tab.silence_max.setValue(10)
    warnings: list[str] = []
    monkeypatch.setattr(
        "aura.ui.tabs.settings_tab.QMessageBox.warning",
        staticmethod(lambda parent, title, text, *args, **kwargs: warnings.append(text)),
    )
    tab.save()
    assert warnings and "Максимум тишины" in warnings[0]
    assert loaded_service.settings.silence_max_sec != 10


def test_transport_via_window_actions(window, loaded_service, qapp):  # noqa: ARG001
    assert {sequence for sequence, _ in SHORTCUTS} >= {"Ctrl+Alt+P", "Ctrl+Alt+L", "Ctrl+Alt+Right"}
    window.trigger("play_next")
    qapp.processEvents()
    assert loaded_service.playlist.current is not None
    window.trigger("like")
    assert loaded_service.library.feedback_totals()["likes"] == 1
    window.trigger("mute")
    assert loaded_service.engine.muted is True
    window.trigger("mute")
    assert loaded_service.engine.muted is False
    window.trigger("show")
    assert window.isVisible()


def test_search_and_import_shortcuts_focus_library(window, qapp):  # noqa: ARG001
    window.trigger("search")
    qapp.processEvents()
    assert window.tabs.currentWidget() is window.library_tab
    assert window.library_tab.search.isEnabled()


def test_tray_controller_states_and_actions(window, loaded_service, qapp):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("системный трей недоступен в этом окружении")

    tray = TrayController(loaded_service, window)
    loaded_service.tray = tray
    track = loaded_service.library.list_tracks()[0]
    loaded_service.playlist.play(track)
    qapp.processEvents()

    assert track.display_title in tray.now_action.text()
    assert track.display_title in tray.icon.toolTip()
    assert "состояние:" in tray.icon.toolTip()

    actions = [action.text() for action in tray.menu.actions()]
    assert any(text in ("Пауза", "Играть") for text in actions)
    assert any(text.startswith("Лайк") for text in actions)
    assert "Выход" in actions

    tray.like_action.trigger()
    qapp.processEvents()
    assert loaded_service.library.latest_feedback(track.id) == 1

    tray.next_action.trigger()
    qapp.processEvents()
    assert loaded_service.playlist.current is not None

    tray._rebuild_pack_filter()
    assert any("music" in action.text() for action in tray.packs_menu.actions())

    tray.autoplay_action.setChecked(False)
    assert loaded_service.playlist.auto_advance is False
    tray.autoplay_action.setChecked(True)
    assert loaded_service.playlist.auto_advance is True

    tray.mute_action.trigger()
    assert loaded_service.engine.muted is True

    tray.hide()
    loaded_service.tray = None


def test_close_to_tray_hides_instead_of_quitting(qapp, loaded_service):  # noqa: ARG001
    loaded_service.settings.close_to_tray = True
    main = MainWindow(loaded_service)
    tray = FakeTray()
    loaded_service.tray = tray
    main.show()
    qapp.processEvents()

    main.closeEvent(QCloseEvent())
    assert main.isVisible() is False
    assert main.quit_requested is False
    assert tray.notes and "трей" in tray.notes[0][0].lower()

    main.show()
    main.closeEvent(QCloseEvent())  # повторную подсказку не показываем
    assert len(tray.notes) == 1

    loaded_service.tray = None
    main.quit()
    assert main.quit_requested is True


def test_close_opens_when_tray_disabled(qapp, loaded_service):  # noqa: ARG001
    loaded_service.settings.close_to_tray = False
    main = MainWindow(loaded_service)
    main.show()
    qapp.processEvents()
    main.closeEvent(QCloseEvent())
    assert main.quit_requested is True
    main.deleteLater()


def test_apply_settings_hot_swaps_scheduler(loaded_service):
    loaded_service.settings.scheduler_backend = "thompson"
    loaded_service.apply_settings()
    assert loaded_service.scheduler_name == "random"  # бэкенд фазы 4 — фолбэк
    assert loaded_service.playlist.scheduler_name == "random"
    assert loaded_service.set_scheduler("random") == "random"
    assert save_settings(loaded_service.settings, loaded_service.paths).exists()


def test_create_app_configures_qapp(qapp):  # noqa: ARG001
    from aura.app import create_app

    app = create_app([])
    assert isinstance(app, QApplication)
    assert app.styleSheet().strip() != ""
    assert app.applicationName() == "Aura"
    assert app.quitOnLastWindowClosed() is False
