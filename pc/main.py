import sys
import serial
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

# ---------------- CONFIG ----------------
PORT = "/dev/ttyACM0"
BAUD = 115200

N_SAMPLES = 1024
VREF = 3.3
SAMPLE_RATE = 100000
# ----------------------------------------

# ---------------- GUI INIT FIRST ----------------
app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(title="pScope Oscilloscope")
plot = win.addPlot(title="Waveform")

plot.setLabel('left', 'Voltage', units='V')
plot.setLabel('bottom', 'Time', units='s')
plot.setYRange(0, 3.3)

curve = plot.plot(pen='g')

win.show()

# ---------------- SERIAL INIT ----------------
try:
    ser = serial.Serial(PORT, BAUD, timeout=1)
    print("Serial connected")
except Exception as e:
    print("Serial error:", e)
    ser = None


# ---------------- READ FUNCTION ----------------
def read_frame():
    if ser is None:
        return None

    try:
        # sync word
        while True:
            b = ser.read(2)
            if len(b) < 2:
                return None
            if b[0] == 0x5A and b[1] == 0xA5:
                break

        raw = ser.read(N_SAMPLES * 2)
        if len(raw) != N_SAMPLES * 2:
            return None

        return np.frombuffer(raw, dtype=np.uint16)

    except Exception as e:
        print("Read error:", e)
        return None


# ---------------- UPDATE LOOP ----------------
def update():
    samples = read_frame()
    if samples is None:
        return

    voltage = (samples / 4095.0) * VREF
    t = np.arange(N_SAMPLES) / SAMPLE_RATE

    curve.setData(t, voltage)


timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(20)


# ---------------- START APP ----------------
sys.exit(app.exec())