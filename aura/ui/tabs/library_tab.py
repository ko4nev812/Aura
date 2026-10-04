"""«Библиотека» — дерево Паки → Треки с тумблерами, DnD и импортом (ТЗ §3.1, §4.1.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QEvent, QMimeData, QPoint, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.service import AuraService
from ...library.manager import ImportResult, PackInfo, TrackInfo
from ...library.scanner import is_audio_file
from ..theme import transport_icon
from ..widgets import format_duration

PACK_ROLE = Qt.ItemDataRole.UserRole + 1
TRACK_ROLE = Qt.ItemDataRole.UserRole + 2
PACK_ID_ROLE = Qt.ItemDataRole.UserRole + 3
TRACK_ID_ROLE = Qt.ItemDataRole.UserRole + 4

COLUMNS = ("Название", "Исполнитель", "Длит.", "Формат", "BPM", "Energy", "Настроение", "Файл")
NEW_PACK = "— новый пак —"
GREY = QColor("#65657f")
VIOLET = QColor("#cbbcff")
RED = QColor("#f87171")


class ImportProgressDialog(QDialog):
    """Прогресс импорта с кнопкой отмены (ТЗ §3.2 UI-поток)."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Импорт")
        self.setModal(True)
        self.resize(440, 120)
        self._cancel_requested = False

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.label = QLabel(title)
        layout.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.request_cancel)
        layout.addWidget(buttons)

    def request_cancel(self) -> None:
        self._cancel_requested = True
        self.label.setText("Отменяю…")

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def update_progress(self, index: int, total: int, path: Path) -> bool:
        """Callback for ``LibraryManager.import_directory``; ``False`` = cancel."""
        self.bar.setValue(int(index / max(1, total) * 100))
        self.label.setText(f"{index} из {total}: {path.name}")
        QApplication.processEvents()
        return not self.cancel_requested


class PackTargetDialog(QDialog):
    """Куда импортировать: существующий пак или новый, копировать ли файлы."""

    def __init__(self, packs: list[PackInfo], suggested_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Импорт папки")
        layout = QVBoxLayout(self)
        layout.setSpacing(9)
        layout.addWidget(QLabel("Добавить треки в пак:"))

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItem(NEW_PACK)
        for pack in packs:
            self.combo.addItem(pack.name, pack.id)
        self.combo.setCurrentIndex(0)
        self.combo.lineEdit().setPlaceholderText(suggested_name)
        self.combo.currentIndexChanged.connect(self._on_index)
        layout.addWidget(self.combo)

        self.copy_files = QCheckBox("Копировать файлы в папку библиотеки Aura")
        self.copy_files.setToolTip(
            "Поиск треков будет вестись по исходной папке (не дублирует файлы), "
            "если галочка снята."
        )
        layout.addWidget(self.copy_files)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_index(self, index: int) -> None:
        if self.combo.itemData(index) is None:
            self.combo.setCurrentText("")

    @property
    def pack_id(self) -> str | None:
        data = self.combo.currentData()
        return str(data) if data else None

    @property
    def pack_name(self) -> str | None:
        return None if self.pack_id else (self.combo.currentText().strip() or None)


class LibraryTree(QTreeWidget):
    """DnD: перемещение треков между паками + импорт файлов из проводника."""

    def __init__(self, on_move: Callable[[list[str], str], None], on_files: Callable[[list[Path]], None], parent=None) -> None:
        super().__init__(parent)
        self._on_move = on_move
        self._on_files = on_files
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.viewport().setAcceptDrops(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        if self._dropped_paths(event) or self.selectedItems():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        event.acceptProposedAction()

    def dropEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt API
        paths = self._dropped_paths(event)
        if paths:
            self._on_files(paths)
            event.acceptProposedAction()
            return

        track_ids = self._dragged_track_ids()
        target_pack = self._target_pack_id(event.pos())
        if track_ids and target_pack:
            self._on_move(track_ids, target_pack)
        event.acceptProposedAction()

    def _dropped_paths(self, event: QEvent) -> list[Path]:
        mime = event.mimeData() if hasattr(event, "mimeData") else QMimeData()
        if not mime.hasUrls():
            return []
        return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]

    def _dragged_track_ids(self) -> list[str]:
        ids: list[str] = []
        for item in self.selectedItems():
            value = item.data(0, TRACK_ID_ROLE)
            if value:
                ids.append(str(value))
        return ids

    def _target_pack_id(self, position: QPoint) -> str | None:
        item = self.itemAt(position)
        while item is not None:
            pack_id = item.data(0, PACK_ID_ROLE)
            if pack_id and item.data(0, PACK_ROLE):
                return str(pack_id)
            item = item.parent()
        return None


class LibraryTab(QWidget):
    def __init__(self, service: AuraService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addLayout(self._build_toolbar())

        self.tree = LibraryTree(self._move_tracks, self._import_files)
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(COLUMNS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for index in range(1, 7):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.tree, 1)

        self.status = QLabel("—")
        self.status.setObjectName("hint")
        root.addWidget(self.status)

        self.reload()

    # ---------------------------------------------------------------- toolbar

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.import_button = QPushButton("Сканировать папку…")
        self.import_button.setObjectName("primary")
        self.import_button.setToolTip("Рекурсивный импорт аудио из папки (Ctrl+I)")
        self.import_button.clicked.connect(self.import_folder)
        row.addWidget(self.import_button)

        self.youtube_button = QPushButton(transport_icon("youtube", 18), "Добавить с YouTube")
        self.youtube_button.setToolTip("Будет доступно в фазе 2 (yt-dlp)")
        self.youtube_button.setEnabled(False)
        row.addWidget(self.youtube_button)

        self.new_pack_button = QPushButton("Новый пак")
        self.new_pack_button.clicked.connect(self.create_pack)
        row.addWidget(self.new_pack_button)

        self.play_button = QPushButton("Играть выбранное")
        self.play_button.clicked.connect(self.play_selection)
        row.addWidget(self.play_button)

        row.addStretch()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: название, исполнитель, тег (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(lambda _text: self.reload())
        row.addWidget(self.search)

        self.enabled_only = QCheckBox("только включённые")
        self.enabled_only.toggled.connect(lambda _value: self.reload())
        row.addWidget(self.enabled_only)
        return row

    # ------------------------------------------------------------------ views

    def reload(self, *, keep_selection: bool = True) -> None:
        selected_track = self._selected_track_id() if keep_selection else None
        expanded = self._expanded_pack_ids()
        query = (self.search.text() or "").strip().lower()
        only_enabled = self.enabled_only.isChecked()

        self._updating = True
        self.tree.clear()
        matches = 0
        for pack in self.service.library.list_packs():
            tracks = [
                track
                for track in pack.tracks
                if (not only_enabled or track.enabled) and _matches(track, query)
            ]
            if (query or only_enabled) and not tracks and query not in pack.name.lower():
                continue
            matches += len(tracks)
            pack_item = QTreeWidgetItem([pack.name])
            pack_item.setData(0, PACK_ROLE, pack.id)
            pack_item.setData(0, PACK_ID_ROLE, pack.id)
            pack_item.setText(2, format_duration(sum(t.duration_sec for t in pack.tracks)))
            pack_item.setText(6, f"{pack.enabled_count}/{pack.track_count} вкл")
            pack_item.setText(7, f"источник: {pack.source}")
            pack_item.setFlags(pack_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            pack_item.setCheckState(0, Qt.CheckState.Checked if pack.enabled else Qt.CheckState.Unchecked)
            font = QFont()
            font.setBold(True)
            pack_item.setFont(0, font)
            pack_item.setForeground(0, VIOLET if pack.enabled else GREY)

            for track in sorted(tracks, key=lambda item: item.title.lower()):
                child = QTreeWidgetItem(_track_columns(track))
                child.setData(0, TRACK_ROLE, track.id)
                child.setData(0, TRACK_ID_ROLE, track.id)
                child.setData(0, PACK_ID_ROLE, pack.id)
                child.setFlags(
                    child.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsDragEnabled
                )
                child.setCheckState(0, Qt.CheckState.Checked if track.enabled else Qt.CheckState.Unchecked)
                child.setToolTip(0, track.file_path)
                if not track.exists:
                    child.setForeground(0, RED)
                elif not track.enabled or not pack.enabled:
                    for column in range(len(COLUMNS)):
                        child.setForeground(column, GREY)
                pack_item.addChild(child)

            self.tree.addTopLevelItem(pack_item)
            pack_item.setExpanded(pack.id in expanded or not expanded)

        self._updating = False
        stats = self.service.library.stats()
        text = (
            f"Паков: {stats['packs']} · треков: {stats['tracks']} · "
            f"включено: {stats['playable']} · общая длительность: {format_duration(stats['duration_sec'])}"
        )
        if query or only_enabled:
            text += f" · подходит фильтру: {matches}"
        self.status.setText(text)
        if selected_track:
            item = self._find_track(selected_track)
            if item is not None:
                self.tree.setCurrentItem(item)

    # ----------------------------------------------------------------- actions

    def import_folder(self) -> None:
        start = self.service.paths.library
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку с музыкой", str(start if start.exists() else Path.home())
        )
        if not folder:
            return
        packs = self.service.library.list_packs(with_tracks=False)
        dialog = PackTargetDialog(packs, Path(folder).name or "Импорт", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pack_name = dialog.pack_name
        if pack_name is None and dialog.pack_id is None:
            self.status.setText("Не задано имя нового пака")
            return
        self._run_import(folder, pack_id=dialog.pack_id, pack_name=pack_name, copy_files=dialog.copy_files.isChecked())

    def _run_import(self, folder: str | Path, *, pack_id: str | None, pack_name: str | None, copy_files: bool) -> None:
        progress = ImportProgressDialog(f"Импорт из {Path(str(folder)).name}", self)
        progress.show()
        QApplication.processEvents()
        try:
            result: ImportResult = self.service.import_directory(
                folder,
                pack_id=pack_id,
                pack_name=pack_name,
                copy_files=copy_files,
                on_progress=progress.update_progress,
            )
        finally:
            progress.accept()
        self.reload()
        if result.errors:
            QMessageBox.warning(
                self,
                "Импорт завершён с замечаниями",
                result.message + "\n\n" + "\n".join(result.errors[:10]),
            )
        self.status.setText(result.message)

    def _import_files(self, paths: list[Path]) -> None:
        files = [path for path in paths if is_audio_file(path)]
        if not files:
            self.status.setText("Перетащите аудиофайлы (mp3, flac, ogg, opus, m4a, wav)")
            return

        selected = self._selected_pack()
        pack_id = selected.id if selected else None
        pack_name = selected.name if selected else None
        if pack_id is None:
            name, ok = QInputDialog.getText(self, "Новый пак", "Название пака:", text="Импорт")
            if not ok or not name.strip():
                return
            pack_name = name.strip()

        imported = 0
        for path in files:
            try:
                if self.service.library.add_local_file(path, pack_id or self._ensure_pack(pack_name)) is not None:
                    imported += 1
            except (OSError, ValueError, KeyError) as exc:
                self.status.setText(f"Не удалось добавить {path.name}: {exc}")
                return
        if pack_name is None and selected is not None:
            pack_name = selected.name
        self.reload(keep_selection=False)
        self.status.setText(f"Добавлено {imported} из {len(files)} в пак «{pack_name or '?'}»")

    def _ensure_pack(self, name: str | None) -> str:
        return self.service.library.create_pack(name or "Импорт").id

    def create_pack(self) -> None:
        name, ok = QInputDialog.getText(self, "Новый пак", "Название пака:")
        if not ok or not name.strip():
            return
        pack = self.service.library.create_pack(name.strip())
        self.reload(keep_selection=False)
        self.status.setText(f"Пак «{pack.name}» создан")

    def play_selection(self) -> None:
        tracks = self.selected_tracks()
        if not tracks:
            self.status.setText("Выберите трек или пак")
            return
        self.service.playlist.play_many(tracks)
        self.status.setText(f"Играем выбранное: {len(tracks)} трек(ов)")

    def selected_tracks(self) -> list[TrackInfo]:
        result: list[TrackInfo] = []
        for item in self.tree.selectedItems():
            if item.data(0, PACK_ROLE):
                pack = self.service.library.get_pack(str(item.data(0, PACK_ID_ROLE)))
                if pack:
                    result.extend(t for t in pack.tracks if t.enabled and t.exists)
                continue
            track_id = item.data(0, TRACK_ID_ROLE)
            if track_id:
                track = self.service.library.get_track(str(track_id))
                if track:
                    result.append(track)
        return result

    def _selected_pack(self) -> PackInfo | None:
        for item in self.tree.selectedItems():
            pack_id = item.data(0, PACK_ID_ROLE)
            if pack_id:
                return self.service.library.get_pack(str(pack_id))
        return None

    # -------------------------------------------------------------- tree events

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        if item.data(0, PACK_ROLE):
            self.service.library.set_pack_enabled(str(item.data(0, PACK_ID_ROLE)), checked)
        elif item.data(0, TRACK_ID_ROLE):
            self.service.library.set_track_enabled(str(item.data(0, TRACK_ID_ROLE)), checked)
        self.reload()

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, PACK_ROLE):
            item.setExpanded(not item.isExpanded())
            return
        track = self.service.library.get_track(str(item.data(0, TRACK_ID_ROLE))) if item.data(0, TRACK_ID_ROLE) else None
        if track is None:
            return
        if not track.exists:
            self.status.setText(f"Файл недоступен: {track.file_path}")
            return
        self.service.playlist.play(track)

    def _move_tracks(self, track_ids: list[str], target_pack_id: str) -> None:
        moved = 0
        for track_id in track_ids:
            if self.service.library.move_track(track_id, target_pack_id) is not None:
                moved += 1
        self.reload()
        pack = self.service.library.get_pack(target_pack_id)
        self.status.setText(f"Перемещено {moved} трек(ов) в «{pack.name if pack else '?'}»")

    # ------------------------------------------------------------ context menu

    def _show_context_menu(self, position: QPoint) -> None:
        item = self.tree.itemAt(position)
        menu = QMenu(self)
        if item is None:
            menu.addAction("Сканировать папку…", self.import_folder)
            menu.addAction("Новый пак", self.create_pack)
            menu.exec(self.tree.viewport().mapToGlobal(position))
            return

        pack_id = str(item.data(0, PACK_ID_ROLE) or "")
        if item.data(0, PACK_ROLE):
            pack = self.service.library.get_pack(pack_id)
            menu.addAction("Играть пак", lambda: self._play_pack(pack_id))
            menu.addAction("Добавить пак в очередь", lambda: self._enqueue_pack(pack_id))
            menu.addSeparator()
            menu.addAction("Переименовать пак", lambda: self._rename_pack(pack_id))
            self._add_move_targets(menu, pack_id, track_id=None)
            menu.addAction("Удалить пак", lambda: self._delete_pack(pack_id))
            if pack:
                menu.addSeparator()
                info = menu.addAction(f"Треков: {pack.track_count} (вкл {pack.enabled_count})")
                info.setEnabled(False)
        else:
            track = self.service.library.get_track(str(item.data(0, TRACK_ID_ROLE)))
            if track is None:
                return
            menu.addAction("Играть сейчас", lambda: self.service.playlist.play(track))
            menu.addAction("Добавить в очередь", lambda: self.service.playlist.enqueue(track))
            menu.addSeparator()
            self._add_move_targets(menu, track.pack_id, track_id=track.id)
            menu.addAction("Показать в проводнике", lambda: self._reveal(track.file_path))
            menu.addAction("Удалить из библиотеки", lambda: self._delete_track(track.id))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _add_move_targets(self, menu: QMenu, current_pack_id: str, *, track_id: str | None) -> None:
        submenu = menu.addMenu("Переместить в пак…")
        others = [pack for pack in self.service.library.list_packs(with_tracks=False) if pack.id != current_pack_id]
        if not others:
            submenu.setDisabled(True)
            return
        for pack in others:
            submenu.addAction(
                pack.name,
                lambda _checked=False, target=pack.id, source=track_id: self._move_single_or_pack(source, target),
            )

    def _move_single_or_pack(self, track_id: str | None, target_pack_id: str) -> None:
        if track_id:
            self._move_tracks([track_id], target_pack_id)
            return
        pack = self.service.library.get_pack(target_pack_id)
        current = self._selected_pack()
        if pack is None or current is None:
            return
        self._move_tracks([t.id for t in current.tracks], target_pack_id)

    def _play_pack(self, pack_id: str) -> None:
        pack = self.service.library.get_pack(pack_id)
        if pack is None:
            return
        tracks = [t for t in pack.tracks if t.enabled and t.exists]
        if not tracks:
            self.status.setText(f"В паке «{pack.name}» нет включённых файлов")
            return
        self.service.playlist.set_pack_filter(pack_id)
        self.service.playlist.play_many(tracks)

    def _enqueue_pack(self, pack_id: str) -> None:
        pack = self.service.library.get_pack(pack_id)
        if pack is None:
            return
        queued = 0
        playing_id = self.service.playlist.current.id if self.service.playlist.current else None
        for track in pack.tracks:
            if track.enabled and track.exists and track.id != playing_id:
                self.service.playlist.enqueue(track)
                queued += 1
        self.status.setText(f"Пак «{pack.name}»: в очереди {queued} трек(ов)")

    def _rename_pack(self, pack_id: str) -> None:
        pack = self.service.library.get_pack(pack_id)
        if pack is None:
            return
        name, ok = QInputDialog.getText(self, "Переименовать пак", "Новое название:", text=pack.name)
        if not ok or not name.strip() or name.strip() == pack.name:
            return
        self.service.library.rename_pack(pack_id, name.strip())
        self.reload()

    def _delete_pack(self, pack_id: str) -> None:
        pack = self.service.library.get_pack(pack_id)
        if pack is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить пак?",
            f"Удалить пак «{pack.name}» ({pack.track_count} записей) из библиотеки?\n"
            "Файлы на диске останутся нетронутыми.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.service.library.delete_pack(pack_id)
        if self.service.playlist.pack_filter == pack_id:
            self.service.playlist.set_pack_filter(None)
        self.reload(keep_selection=False)
        self.status.setText(f"Пак «{pack.name}» удалён")

    def _delete_track(self, track_id: str) -> None:
        self.service.library.delete_track(track_id)
        self.reload()
        self.status.setText("Трек удалён из библиотеки (файл на диске не тронут)")

    def _reveal(self, file_path: str) -> None:
        from ...win_util import reveal_in_explorer

        reveal_in_explorer(file_path)

    # ------------------------------------------------------ selection utilities

    def _selected_track_id(self) -> str | None:
        for item in self.tree.selectedItems():
            value = item.data(0, TRACK_ID_ROLE)
            if value:
                return str(value)
        return None

    def _expanded_pack_ids(self) -> set[str]:
        return {
            str(item.data(0, PACK_ID_ROLE))
            for item in (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
            if item is not None and item.isExpanded()
        }

    def _find_track(self, track_id: str) -> QTreeWidgetItem | None:
        for pack_index in range(self.tree.topLevelItemCount()):
            pack_item = self.tree.topLevelItem(pack_index)
            if pack_item is None:
                continue
            for child_index in range(pack_item.childCount()):
                child = pack_item.child(child_index)
                if child is not None and str(child.data(0, TRACK_ID_ROLE)) == track_id:
                    return child
        return None

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()


def _track_columns(track: TrackInfo) -> list[str]:
    return [
        track.title + ("" if track.exists else "  ⟂ файл отсутствует"),
        track.artist or "",
        format_duration(track.duration_sec),
        (track.format or "").upper(),
        f"{track.bpm:.0f}" if track.bpm else "—",
        f"{track.energy:.2f}" if track.energy is not None else "—",
        ", ".join(track.mood_tags[:3]) or "—",
        Path(track.file_path).name,
    ]


def _matches(track: TrackInfo, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        part for part in (track.title, track.artist or "", " ".join(track.mood_tags)) if part
    ).lower()
    return query in haystack
