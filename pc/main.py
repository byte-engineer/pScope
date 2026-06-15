import sys
import struct
import time
import numpy as np
import serial
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT = "/dev/ttyACM0"
BAUD = 115200

N_SAMPLES = 1024
VREF = 3.3
ADC_MAX = 4095
SAMPLE_RATE = 100000

SYNC_WORD = 0xA55A
SYNC_BYTES = struct.pack('<H', SYNC_WORD)
FRAME_BYTES = N_SAMPLES * 2
HALF = N_SAMPLES // 2

DEFAULT_TRIGGER_V = 1.0


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
BG_COLOR = "#1e1e2e"
FG_COLOR = "#cdd6f4"
ACCENT = "#89b4fa"
GOOD = "#a6e3a1"
BAD = "#f38ba8"
GRID_COLOR = "#45475a"
CURVE_COLOR = "#a6e3a1"
FFT_COLOR = "#89b4fa"

pg.setConfigOption('background', BG_COLOR)
pg.setConfigOption('foreground', FG_COLOR)
pg.setConfigOptions(antialias=True)

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG_COLOR};
    color: {FG_COLOR};
    font-family: "Segoe UI", "Cantarell", sans-serif;
    font-size: 10.5pt;
}}
QGroupBox {{
    border: 1px solid {GRID_COLOR};
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {ACCENT};
}}
QPushButton {{
    background-color: #313244;
    border: 1px solid {GRID_COLOR};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background-color: #45475a;
}}
QPushButton:checked {{
    background-color: {ACCENT};
    color: {BG_COLOR};
    font-weight: 600;
}}
QDoubleSpinBox {{
    background-color: #313244;
    border: 1px solid {GRID_COLOR};
    border-radius: 4px;
    padding: 3px 6px;
}}
QStatusBar {{
    background-color: #181825;
}}
QLabel#title {{
    font-size: 15pt;
    font-weight: 700;
    color: {FG_COLOR};
}}
QLabel#measValue {{
    color: {ACCENT};
    font-weight: 600;
    font-family: "Consolas", "DejaVu Sans Mono", monospace;
}}
"""


class ScopeWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pScope \u2014 RP2040 Oscilloscope")
        self.resize(1150, 680)
        self.setMinimumSize(900, 550)
        self.setStyleSheet(STYLESHEET)

        self.rx_buf = bytearray()
        self.history = np.zeros(N_SAMPLES * 2, dtype=np.uint16)
        self.running = True
        self.trigger_level_v = DEFAULT_TRIGGER_V

        self.t = np.arange(N_SAMPLES) / SAMPLE_RATE
        self.t_ms = self.t * 1e3
        self.freqs = np.fft.rfftfreq(N_SAMPLES, d=1.0 / SAMPLE_RATE)
        self.fft_window = np.hanning(N_SAMPLES)

        self.ser = None

        self._build_ui()
        self.connect_serial()

        self._frame_count = 0
        self._last_fps_time = time.monotonic()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(20)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ---- left: plots ---------------------------------------------
        plot_container = QtWidgets.QVBoxLayout()
        plot_container.setSpacing(8)

        title = QtWidgets.QLabel("RP2040 Oscilloscope")
        title.setObjectName("title")
        plot_container.addWidget(title)

        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel('left', 'Voltage', units='V')
        self.plot.setLabel('bottom', 'Time', units='ms')
        self.plot.setYRange(0, VREF)
        self.plot.setXRange(self.t_ms[0], self.t_ms[-1])

        self.curve = self.plot.plot(pen=pg.mkPen(CURVE_COLOR, width=2))
        self.trigger_marker = self.plot.plot(
            pen=None, symbol='o', symbolSize=8,
            symbolBrush=BAD, symbolPen=None
        )

        self.trigger_line = pg.InfiniteLine(
            pos=self.trigger_level_v,
            angle=0,
            movable=True,
            pen=pg.mkPen(BAD, width=1.5),
            label='{value:.2f} V',
            labelOpts={'position': 0.97, 'color': BAD}
        )
        self.trigger_line.sigPositionChangeFinished.connect(self._on_trigger_line_moved)
        self.plot.addItem(self.trigger_line)

        # crosshair
        self.v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(GRID_COLOR, width=1))
        self.h_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(GRID_COLOR, width=1))
        self.v_line.setVisible(False)
        self.h_line.setVisible(False)
        self.plot.addItem(self.v_line, ignoreBounds=True)
        self.plot.addItem(self.h_line, ignoreBounds=True)

        self.cursor_label = pg.TextItem(anchor=(0, 1), color=FG_COLOR)
        self.plot.addItem(self.cursor_label)

        self.proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved, rateLimit=60, slot=self._mouse_moved
        )

        self.fft_plot = pg.PlotWidget()
        self.fft_plot.setMenuEnabled(False)
        self.fft_plot.showGrid(x=True, y=True, alpha=0.25)
        self.fft_plot.setLabel('left', 'Magnitude', units='dB')
        self.fft_plot.setLabel('bottom', 'Frequency', units='Hz')
        self.fft_plot.setXRange(0, SAMPLE_RATE / 2)
        self.fft_curve = self.fft_plot.plot(pen=pg.mkPen(FFT_COLOR, width=1.5))

        plot_container.addWidget(self.plot, 4)
        plot_container.addWidget(self.fft_plot, 1)

        root.addLayout(plot_container, 4)

        # ---- right: control panel --------------------------------------
        side = QtWidgets.QVBoxLayout()
        side.setSpacing(12)

        # Trigger group
        trig_group = QtWidgets.QGroupBox("Trigger")
        trig_layout = QtWidgets.QFormLayout(trig_group)
        self.trigger_spin = QtWidgets.QDoubleSpinBox()
        self.trigger_spin.setRange(0.0, VREF)
        self.trigger_spin.setSingleStep(0.05)
        self.trigger_spin.setDecimals(2)
        self.trigger_spin.setSuffix(" V")
        self.trigger_spin.setValue(self.trigger_level_v)
        self.trigger_spin.valueChanged.connect(self._on_trigger_spin_changed)
        trig_layout.addRow("Level", self.trigger_spin)
        side.addWidget(trig_group)

        # Acquisition group
        acq_group = QtWidgets.QGroupBox("Acquisition")
        acq_layout = QtWidgets.QVBoxLayout(acq_group)

        self.run_button = QtWidgets.QPushButton("\u23F8  Pause")
        self.run_button.setCheckable(True)
        self.run_button.toggled.connect(self._toggle_run)
        acq_layout.addWidget(self.run_button)

        self.autoscale_button = QtWidgets.QPushButton("Autoscale Y")
        self.autoscale_button.clicked.connect(self._autoscale)
        acq_layout.addWidget(self.autoscale_button)

        self.save_button = QtWidgets.QPushButton("Save Capture (CSV)")
        self.save_button.clicked.connect(self._save_csv)
        acq_layout.addWidget(self.save_button)

        self.reconnect_button = QtWidgets.QPushButton("Reconnect")
        self.reconnect_button.clicked.connect(self.connect_serial)
        acq_layout.addWidget(self.reconnect_button)

        side.addWidget(acq_group)

        # Measurements group
        meas_group = QtWidgets.QGroupBox("Measurements")
        meas_layout = QtWidgets.QFormLayout(meas_group)
        self.meas_labels = {}
        for name in ("Vmax", "Vmin", "Vpp", "Vavg", "Freq"):
            value_label = QtWidgets.QLabel("--")
            value_label.setObjectName("measValue")
            meas_layout.addRow(name, value_label)
            self.meas_labels[name] = value_label
        side.addWidget(meas_group)

        side.addStretch(1)

        side_widget = QtWidgets.QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(230)
        root.addWidget(side_widget, 0)

        # ---- status bar ---------------------------------------------
        self.status = self.statusBar()
        self.conn_label = QtWidgets.QLabel("Disconnected")
        self.fps_label = QtWidgets.QLabel("-- fps")
        self.status.addWidget(self.conn_label, 1)
        self.status.addPermanentWidget(self.fps_label)

    # ------------------------------------------------------------------
    # Serial handling
    # ------------------------------------------------------------------
    def connect_serial(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass

        try:
            self.ser = serial.Serial(PORT, BAUD, timeout=0)
            self.ser.reset_input_buffer()
            self.rx_buf.clear()
            self.conn_label.setText(f"Connected: {PORT}")
            self.conn_label.setStyleSheet(f"color: {GOOD};")
        except (serial.SerialException, OSError) as exc:
            self.ser = None
            self.conn_label.setText(f"Disconnected ({exc})")
            self.conn_label.setStyleSheet(f"color: {BAD};")

    def read_frame(self):
        """Read one sample frame, resyncing on SYNC_BYTES if needed."""
        if self.ser is None:
            return None

        try:
            chunk = self.ser.read(4096)
        except (serial.SerialException, OSError):
            self.ser = None
            self.conn_label.setText("Disconnected (read error)")
            self.conn_label.setStyleSheet(f"color: {BAD};")
            return None

        if chunk:
            self.rx_buf.extend(chunk)

        idx = self.rx_buf.find(SYNC_BYTES)
        if idx == -1:
            # No sync word found yet; keep only the last byte in case a
            # sync word is split across two reads.
            if len(self.rx_buf) > 1:
                del self.rx_buf[:-1]
            return None

        if idx > 0:
            del self.rx_buf[:idx]

        needed = len(SYNC_BYTES) + FRAME_BYTES
        if len(self.rx_buf) < needed:
            return None

        payload = bytes(self.rx_buf[len(SYNC_BYTES):needed])
        del self.rx_buf[:needed]

        return np.frombuffer(payload, dtype='<u2')

    # ------------------------------------------------------------------
    # Signal processing
    # ------------------------------------------------------------------
    @staticmethod
    def find_trigger(samples_arr, level):
        for i in range(1, len(samples_arr)):
            if samples_arr[i - 1] < level <= samples_arr[i]:
                return i
        return None

    def estimate_frequency(self, voltage):
        crossings = []
        level = self.trigger_level_v
        for i in range(1, len(voltage)):
            if voltage[i - 1] < level <= voltage[i]:
                crossings.append(i)
        if len(crossings) < 2:
            return None
        periods = np.diff(crossings)
        avg_period = float(np.mean(periods))
        if avg_period <= 0:
            return None
        return SAMPLE_RATE / avg_period

    # ------------------------------------------------------------------
    # Main update loop
    # ------------------------------------------------------------------
    def update_plot(self):
        if not self.running:
            return

        frame = self.read_frame()
        if frame is None:
            return

        # Slide the new frame into the rolling history buffer
        self.history = np.concatenate((self.history[N_SAMPLES:], frame))

        level_adc = int((self.trigger_level_v / VREF) * ADC_MAX)

        search = self.history[HALF: len(self.history) - HALF]
        trig = self.find_trigger(search, level_adc)

        if trig is None:
            aligned = self.history[N_SAMPLES:]
            trig_index = None
        else:
            center = HALF + trig
            aligned = self.history[center - HALF: center + HALF]
            trig_index = HALF

        voltage = (aligned.astype(np.float64) / ADC_MAX) * VREF
        self.curve.setData(self.t_ms, voltage)

        if trig_index is not None:
            self.trigger_marker.setData([self.t_ms[trig_index]], [voltage[trig_index]])
        else:
            self.trigger_marker.setData([], [])

        # ---- measurements ----
        vmax = float(np.max(voltage))
        vmin = float(np.min(voltage))
        vpp = vmax - vmin
        vavg = float(np.mean(voltage))
        freq = self.estimate_frequency(voltage)

        self.meas_labels["Vmax"].setText(f"{vmax:.3f} V")
        self.meas_labels["Vmin"].setText(f"{vmin:.3f} V")
        self.meas_labels["Vpp"].setText(f"{vpp:.3f} V")
        self.meas_labels["Vavg"].setText(f"{vavg:.3f} V")
        if freq is not None:
            if freq >= 1000:
                self.meas_labels["Freq"].setText(f"{freq / 1000:.3f} kHz")
            else:
                self.meas_labels["Freq"].setText(f"{freq:.1f} Hz")
        else:
            self.meas_labels["Freq"].setText("--")

        # ---- spectrum ----
        spectrum = np.abs(np.fft.rfft((voltage - vavg) * self.fft_window))
        spectrum_db = 20 * np.log10(spectrum + 1e-9)
        self.fft_curve.setData(self.freqs, spectrum_db)

        # ---- fps ----
        self._frame_count += 1
        now = time.monotonic()
        elapsed = now - self._last_fps_time
        if elapsed >= 0.5:
            fps = self._frame_count / elapsed
            self.fps_label.setText(f"{fps:.1f} fps")
            self._frame_count = 0
            self._last_fps_time = now

    # ------------------------------------------------------------------
    # UI callbacks
    # ------------------------------------------------------------------
    def _on_trigger_spin_changed(self, value):
        self.trigger_level_v = value
        self.trigger_line.blockSignals(True)
        self.trigger_line.setPos(value)
        self.trigger_line.blockSignals(False)

    def _on_trigger_line_moved(self):
        value = self.trigger_line.value()
        value = max(0.0, min(VREF, value))
        self.trigger_level_v = value
        self.trigger_spin.blockSignals(True)
        self.trigger_spin.setValue(value)
        self.trigger_spin.blockSignals(False)

    def _toggle_run(self, checked):
        self.running = not checked
        self.run_button.setText("\u25B6  Run" if checked else "\u23F8  Pause")

    def _autoscale(self):
        self.plot.enableAutoRange(axis=pg.ViewBox.YAxis)

    def _save_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Capture", "capture.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        x_data, y_data = self.curve.getData()
        if x_data is None:
            return
        data = np.column_stack((np.asarray(x_data) / 1e3, y_data))  # ms -> s
        np.savetxt(path, data, delimiter=",", header="time_s,voltage_v", comments="")

    def _mouse_moved(self, evt):
        pos = evt[0]
        vb = self.plot.getViewBox()
        if self.plot.sceneBoundingRect().contains(pos):
            mouse_point = vb.mapSceneToView(pos)
            x, y = mouse_point.x(), mouse_point.y()
            self.v_line.setPos(x)
            self.h_line.setPos(y)
            self.v_line.setVisible(True)
            self.h_line.setVisible(True)
            self.cursor_label.setPos(x, y)
            self.cursor_label.setText(f"t = {x:.3f} ms\nV = {y:.3f} V")
        else:
            self.v_line.setVisible(False)
            self.h_line.setVisible(False)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = ScopeWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()