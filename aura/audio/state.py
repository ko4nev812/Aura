"""Playback state machine (ТЗ §3.5)."""

from __future__ import annotations

from enum import Enum


class PlayerState(str, Enum):
    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"
    FADING_OUT = "fading_out"
    SILENCE = "silence"

    @property
    def is_active(self) -> bool:
        return self in (PlayerState.PLAYING, PlayerState.LOADING, PlayerState.FADING_OUT)

    @property
    def label(self) -> str:
        return {
            PlayerState.IDLE: "Остановлен",
            PlayerState.LOADING: "Загрузка",
            PlayerState.PLAYING: "Играет",
            PlayerState.PAUSED: "Пауза",
            PlayerState.FADING_OUT: "Затухание",
            PlayerState.SILENCE: "Тишина",
        }[self]
