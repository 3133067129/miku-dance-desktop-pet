# pet_window.py
from __future__ import annotations

import time

from PyQt6.QtWidgets import QWidget, QLabel, QGraphicsDropShadowEffect, QFrame, QSlider
from PyQt6.QtCore import Qt, QTimer, QPoint, QSize
from PyQt6.QtGui import QColor, QFont, QKeyEvent

from controller import AppController


class SettingsPanel(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: rgba(0,0,0,140); border-radius: 12px; }"
            "QLabel { color: rgba(255,255,255,230); }"
        )

        self.title = QLabel("Tuning", self)
        tf = QFont()
        tf.setPointSize(10)
        tf.setBold(True)
        self.title.setFont(tf)
        self.title.move(12, 10)

        self.lab_gate = QLabel("Sensitivity (Gate)", self)
        self.lab_gate.move(12, 38)

        self.s_gate = QSlider(Qt.Orientation.Horizontal, self)
        self.s_gate.setGeometry(12, 58, 210, 18)
        self.s_gate.setMinimum(1)    # 0.001
        self.s_gate.setMaximum(80)   # 0.080

        self.val_gate = QLabel("", self)
        self.val_gate.move(230, 54)

        self.lab_hold = QLabel("Hold (s)", self)
        self.lab_hold.move(12, 82)

        self.s_hold = QSlider(Qt.Orientation.Horizontal, self)
        self.s_hold.setGeometry(12, 102, 210, 18)
        self.s_hold.setMinimum(2)    # 0.2
        self.s_hold.setMaximum(80)   # 8.0

        self.val_hold = QLabel("", self)
        self.val_hold.move(230, 98)

        self.setFixedSize(280, 132)

    @staticmethod
    def _gate_slider_to_value(v: int) -> float:
        return v / 1000.0

    @staticmethod
    def _hold_slider_to_value(v: int) -> float:
        return v / 10.0

    @staticmethod
    def _gate_value_to_slider(x: float) -> int:
        return int(round(min(max(x, 0.001), 0.080) * 1000))

    @staticmethod
    def _hold_value_to_slider(x: float) -> int:
        return int(round(min(max(x, 0.2), 8.0) * 10))

    def set_values(self, gate: float, hold: float):
        self.s_gate.setValue(self._gate_value_to_slider(gate))
        self.s_hold.setValue(self._hold_value_to_slider(hold))

    def update_labels(self):
        self.val_gate.setText(f"{self._gate_slider_to_value(self.s_gate.value()):.3f}")
        self.val_hold.setText(f"{self._hold_slider_to_value(self.s_hold.value()):.1f}")


class PetWindow(QWidget):
    """
    第一阶段重构后的 UI：
    - 只做：渲染 + 交互
    - 业务决策（自动切编舞/跟拍 clip/播放推进）全部在 AppController
    """

    def __init__(
        self,
        controller: AppController,
        engine,
        default_size: int = 300,
        target_fps: int = 60,
    ):
        super().__init__()
        self.controller = controller
        self.engine = engine
        self.default_size = int(default_size)

        self.scale = 1.0
        self.drag_offset = QPoint()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(self.default_size, self.default_size)

        # 动画层
        self.label = QLabel(self)
        self.label.setGeometry(0, 0, self.default_size, self.default_size)
        self.label.setScaledContents(False)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(6, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.label.setGraphicsEffect(shadow)

        # Debug overlay
        self.debug_visible = True
        self.debug = QLabel(self)
        self.debug.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.debug.setWordWrap(True)
        self.debug.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.debug.setStyleSheet(
            "QLabel { color: rgba(255,255,255,220); background: rgba(0,0,0,90); "
            "border-radius: 8px; padding: 6px; }"
        )
        font = QFont()
        font.setPointSize(9)
        self.debug.setFont(font)
        self.debug.move(10, 10)
        self.debug.resize(320, 320)

        # Tuning panel
        self.panel = SettingsPanel(self)
        self.panel.hide()
        self.panel.s_gate.valueChanged.connect(self._on_gate_changed)
        self.panel.s_hold.valueChanged.connect(self._on_hold_changed)

        # 预载基础动画（避免首次切换卡顿）
        for clip in ("idle", "dance_slow", "dance_mid", "dance_fast", "accent"):
            try:
                self.controller.bank.load_clip(clip)
            except Exception:
                pass

        # 初始化 panel 数值
        self.panel.set_values(self.engine.get_gate(), self.engine.get_hold())
        self.panel.update_labels()

        # FPS/布局节流
        self._last_layout_t = time.time()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._ui_tick)
        self.timer.start(int(1000 / max(1, int(target_fps))))

        # 初次渲染
        snap = self.controller.render_tick(self.size())
        self.label.setPixmap(snap.pixmap)
        if self.debug_visible:
            self.debug.setText(snap.debug_text)

    def _on_gate_changed(self, _v: int):
        gate = self.panel._gate_slider_to_value(self.panel.s_gate.value())
        self.engine.set_gate(gate)
        self.panel.update_labels()

    def _on_hold_changed(self, _v: int):
        hold = self.panel._hold_slider_to_value(self.panel.s_hold.value())
        self.engine.set_hold(hold)
        self.panel.update_labels()

    def _update_overlay_layout_only(self):
        # 调整 debug/panel 位置，保持不遮挡
        now = time.time()
        if now - self._last_layout_t < 0.05:
            return
        self._last_layout_t = now

        size = self.size()
        w = min(360, max(200, size.width() - 20))
        self.debug.resize(w, 320)
        self.debug.move(10, 10)

        px = max(10, size.width() - self.panel.width() - 10)
        py = max(10, size.height() - self.panel.height() - 10)
        self.panel.move(px, py)

    def _ui_tick(self):
        snap = self.controller.render_tick(self.size())
        self.label.setPixmap(snap.pixmap)
        if self.debug_visible:
            self.debug.setText(snap.debug_text)

    # ---- 快捷键 ----
    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_F1:
            self.debug_visible = not self.debug_visible
            self.debug.setVisible(self.debug_visible)
            e.accept()
            return
        if e.key() == Qt.Key.Key_F2:
            self.panel.setVisible(not self.panel.isVisible())
            e.accept()
            return
        if e.key() == Qt.Key.Key_F3:
            self.controller.toggle_choreo_manual()
            e.accept()
            return
        super().keyPressEvent(e)

    # ---- 拖拽 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()
            self.setFocus()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    # ---- 缩放（保持中心不漂移）----
    def wheelEvent(self, event):
        old_center = self.geometry().center()

        factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        raw_scale = self.scale * factor
        target_size = int(round(self.default_size * raw_scale))
        target_size = max(80, min(target_size, 2000))

        if target_size == self.width() and target_size == self.height():
            event.accept()
            return

        self.scale = target_size / float(self.default_size)

        rect = self.geometry()
        rect.setSize(QSize(target_size, target_size))
        rect.moveCenter(old_center)
        self.setGeometry(rect)

        self.label.setGeometry(0, 0, target_size, target_size)

        # 清缓存：尺寸变动会导致 scaled_cache 维度爆炸
        self.controller.clear_render_cache_on_resize()

        self._update_overlay_layout_only()
        event.accept()

    def closeEvent(self, event):
        self.timer.stop()
        try:
            self.controller.close()
        except Exception:
            pass
        event.accept()
