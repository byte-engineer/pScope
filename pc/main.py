import serial
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

# ---------------- CONFIG ----------------
PORT = "/dev/ttyACM2"
BAUD = 115200
N_SAMPLES = 1024*16
V_REF = 3.3
# ----------------------------------------

ser = serial.Serial(PORT, BAUD)

app = QtWidgets.QApplication([])

win = pg.GraphicsLayoutWidget(title="pScope")
plot = win.addPlot(title="Waveform")
plot.setYRange(0, 128)

curve = plot.plot(pen='y')

win.show()

def update():
    try:
        raw = ser.read(N_SAMPLES * 2)

        samples = np.frombuffer(raw, dtype=np.uint16)

        curve.setData(samples)

    except Exception as e:
        print("Error:", e)

timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(20)   # 50 FPS

app.exec()