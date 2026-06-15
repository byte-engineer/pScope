import serial
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

# ---------------- CONFIG ----------------
PORT = "/dev/ttyACM0"
BAUD = 115200

N_SAMPLES = 1024

VREF = 3.3

# TEMPORARY SAMPLE RATE (we will calibrate later)
SAMPLE_RATE = 100000  # 100 kS/s

DT = 1.0 / SAMPLE_RATE
# ----------------------------------------

ser = serial.Serial(PORT, BAUD)

app = QtWidgets.QApplication([])

win = pg.GraphicsLayoutWidget(title="pScope")
plot = win.addPlot(title="Waveform")

plot.setLabel('left', 'Voltage', units='V')
plot.setLabel('bottom', 'Time', units='s')
plot.setYRange(0, 3.3)

curve = plot.plot(pen='g')

win.show()


def update():
    raw = ser.read(N_SAMPLES * 2)

    samples = np.frombuffer(raw, dtype=np.uint16)

    # Convert ADC → voltage
    voltage = (samples / 256) * VREF

    # Build time axis
    t = np.arange(N_SAMPLES) * DT

    curve.setData(t, voltage)


timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(20)   # ~50 FPS

app.exec()