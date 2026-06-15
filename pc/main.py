import sys
import serial
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

PORT = "/dev/ttyACM0"
BAUD = 115200

N_SAMPLES = 1024
VREF = 3.3
SAMPLE_RATE = 100000

TRIGGER_LEVEL = 1.0  # LOWERED for debugging

ser = serial.Serial(PORT, BAUD, timeout=0.1)

app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(title="pScope")
plot = win.addPlot(title="Signal")

plot.setLabel('left', 'Voltage', units='V')
plot.setLabel('bottom', 'Time', units='s')
plot.setYRange(0, 3.3)

curve = plot.plot(pen='g')
trigger_marker = plot.plot(pen=None, symbol='o', symbolBrush='r')

win.show()

t = np.arange(N_SAMPLES) / SAMPLE_RATE

trigger_line = pg.InfiniteLine(
    pos=TRIGGER_LEVEL,
    angle=0,
    pen=pg.mkPen('r', width=1)
)
plot.addItem(trigger_line)

def read_frame():
    raw = ser.read(N_SAMPLES * 2)
    if len(raw) != N_SAMPLES * 2:
        return None
    return np.frombuffer(raw, dtype=np.uint16)


def find_trigger(samples, level):
    for i in range(1, len(samples)):
        if samples[i-1] < level and samples[i] >= level:
            return i
    return None


def update():
    samples = read_frame()
    if samples is None:
        return

    level_adc = int((TRIGGER_LEVEL / VREF) * 4095)

    trig = find_trigger(samples, level_adc)

    print(samples[:1])

    # fallback: if no trigger, just show raw
    if trig is None:
        aligned = samples
    else:
        half = N_SAMPLES // 2

        start = trig - half
        end = trig + half

        # clamp safely
        if start < 0:
            start = 0
            end = N_SAMPLES
        if end > len(samples):
            end = len(samples)
            start = end - N_SAMPLES

        aligned = samples[start:end]

    voltage = (aligned / 4095.0) * VREF

    curve.setData(t, voltage)



timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(20)

sys.exit(app.exec())