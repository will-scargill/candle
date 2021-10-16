import sys
from os import environ
from PyQt5.QtWidgets import QApplication

from candle import Candle

environ["QT_DEVICE_PIXEL_RATIO"] = "0"
environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
environ["QT_SCREEN_SCALE_FACTORS"] = "1"
environ["QT_SCALE_FACTOR"] = "1"

app = QApplication(sys.argv)

candle = Candle()
candle.show()

app.exec()
