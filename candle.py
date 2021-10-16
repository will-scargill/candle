import sys
import os
import math
from collections import namedtuple
from PyQt5 import QtGui, QtWidgets, QtCore, uic
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFileDialog, QListWidgetItem
from logzero import logger
from sqlalchemy import create_engine
from sqlalchemy.sql.schema import MetaData
from sqlalchemy.exc import IntegrityError

from db import Tags, Files, FileTags

preview = namedtuple("preview", "id title image")

class Candle(QtWidgets.QMainWindow):
    def __init__(self):
        super(Candle, self).__init__()  
        uic.loadUi(os.path.join("ui", "main.ui"), self)

        self.dbconn = None
        self.engine = None

        self.curImageID = None
        self.image = None
        self.timer = None

        self.allImagesView.setAcceptDrops(False) # Doesn't work if only set in Qt Designer 
        self.allImagesView.setDragEnabled(False) # ¯\_(ツ)_/¯

        self.allImagesView.installEventFilter(self)

        # connections
        
        self.actionNew_database.triggered.connect(self.newDatabase)

        self.actionLoad_database.triggered.connect(self.loadDatabase)

        self.actionImport.triggered.connect(self.importFiles)

        self.actionZoom_In.triggered.connect(lambda: self.scaleImage(1.25))

        self.actionZoom_Out.triggered.connect(lambda: self.scaleImage(0.75))

        self.actionFit_to_Window.triggered.connect(lambda: self.scaleImage(1, newScaleFactor=1))

        self.actionExit.triggered.connect(self.exitCandle)

        self.actionAbout_Qt.triggered.connect(QtWidgets.qApp.aboutQt)

        self.changeDisplayButton.clicked.connect(self.changeDisplay)

        self.nextImageButton.clicked.connect(self.nextImage)

        self.prevImageButton.clicked.connect(self.prevImage)

        logger.info("Candle Lit")

        self.stackedWidget.setCurrentIndex(1)

        self.autoLoadDB() # Debug

    def newDatabase(self):
        path, _ = QFileDialog.getSaveFileName(self,"QFileDialog.getSaveFileName()","","SQLite3 (*.db);;All Files (*)")
        self.engine = create_engine(fr"sqlite:///{path}")

        meta = MetaData()

        Files.create(self.engine, checkfirst=True)
        Tags.create(self.engine, checkfirst=True)
        FileTags.create(self.engine, checkfirst=True)

        self.dbconn = self.engine.connect()

        logger.info("Database connected")

        self.refreshTags()

    def loadDatabase(self):
        path, _ = QFileDialog.getOpenFileName(self)

        self.engine = create_engine(fr"sqlite:///{path}")
        self.dbconn = self.engine.connect()

        logger.info("Database connected")

        self.refreshTags()

    def autoLoadDB(self):
        self.engine = create_engine(r"sqlite:///test.db")
        self.dbconn = self.engine.connect()

        logger.info("Database connected")

        self.refreshTags()

    def importFiles(self):
        files, _ = QFileDialog.getOpenFileNames(self)
        for file in files:
            if os.path.isfile(file):
                try:
                    query = Files.insert().values(
                        name = (os.path.split(file))[1],
                        path = file
                    )

                    self.dbconn.execute(query)
                except IntegrityError:
                    logger.error(f"Integrity Error when importing {file}")
                    # Messagebox here
        self.refreshImages()

    def exitCandle(self):
        sys.exit()

    def refreshTags(self):
        query = Tags.select()
        all_tags = (self.dbconn.execute(query)).fetchall()
        
        model = QtGui.QStandardItemModel(self.tagList)
        self.tagList.setModel(model)

        for tag in all_tags:
            tag_item = QtGui.QStandardItem(tag[1])
            tag_item.setCheckable(True)
            model.appendRow(tag_item)

        model.itemChanged.connect(self.onTagChanged)
        self.refreshImages()

    def onTagChanged(self, item):
        self.refreshImages()

    def refreshImages(self):
        self.allImagesView.clear()
        query = Files.select().order_by(Files.c.id.asc())
        all_files = (self.dbconn.execute(query)).fetchall()

        for file in all_files:
            path = file[2]
            name = file[1]
            icon = QtGui.QIcon(path)
            item = QListWidgetItem(icon, name)
            self.allImagesView.addItem(item)

    def changeDisplay(self):
        cur_index = self.stackedWidget.currentIndex()
        if cur_index == 0:
            self.stackedWidget.setCurrentIndex(1)
        elif cur_index == 1:
            self.stackedWidget.setCurrentIndex(0)

    def eventFilter(self, source, event):
        if event.type() == QtCore.QEvent.ContextMenu:
            menu = QtWidgets.QMenu()
            image_display = QtWidgets.QAction("Display image")
            image_delete = QtWidgets.QAction("Delete image")

            menu.addAction(image_display)
            menu.addAction(image_delete)

            menu_click = menu.exec(event.globalPos()) 

            try:
                item = source.itemAt(event.pos())
            except Exception as e:
                print(f"No item selected {e}")

            if menu_click == image_display :
                self.loadSingleImage(item)
            if menu_click == image_delete :
                pass # remove image from db and display

            return True
        elif event.type() == QtCore.QEvent.MouseButtonDblClick:
            print("test")
            return True

        return super(Candle, self).eventFilter(source, event)
    
    def loadSingleImage(self, item):
        query = Files.select().where(Files.c.name == item.text())
        file_data = (self.dbconn.execute(query)).fetchone()
        path = file_data[2]

        self.loadImage(file_data)

    def nextImage(self):
        if self.curImageID:
            i = 1
            while True:
                file_data = self.getImageByID(self.curImageID + i)
                if file_data:
                    break
                else:
                    i += 1

            self.loadImage(file_data)


    def prevImage(self):
        if self.curImageID:
            i = -1
            while True:
                file_data = self.getImageByID(self.curImageID + i)
                if file_data:
                    break
                else:
                    i -= 1

            self.loadImage(file_data)

    def getImageByID(self, id):
        query = Files.select().where(Files.c.id == id)
        
        file_data = (self.dbconn.execute(query)).fetchone()

        return file_data

    def loadImage(self, file_data):
        path = file_data[2]

        self.image = QtGui.QPixmap(path)

        if self.image.isNull():
            QtWidgets.QMessageBox.information(self, "Image Viewer", "Cannot load %s." % file_data[1])
            return

        self.curImageID = file_data[0]

        self.singleImageView.setPixmap(self.image.scaled(self.singleImageView.size(), Qt.KeepAspectRatio, Qt.FastTransformation))


        self.stackedWidget.setCurrentIndex(0)
    
    def resizeEvent(self, event):
        if event.spontaneous() and self.image:
            self.timer = QtCore.QTimer()
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.resizeImage)
            self.timer.start(1)
        
    
    def resizeImage(self):
        self.singleImageView.setPixmap(self.image.scaled(self.singleImageView.size(), Qt.KeepAspectRatio, Qt.FastTransformation))