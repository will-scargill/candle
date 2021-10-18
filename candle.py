from operator import and_
import sys
import os
import math
from collections import namedtuple
from PyQt5 import QtGui, QtWidgets, QtCore, uic
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImageIOHandler, QMovie
from PyQt5.QtWidgets import QFileDialog, QListWidgetItem
from logzero import logger
from sqlalchemy import create_engine, func, and_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from db import Base
from alchemy import Tags, Files, FileTags

preview = namedtuple("preview", "id title image")

class Candle(QtWidgets.QMainWindow):
    def __init__(self):
        super(Candle, self).__init__()  
        uic.loadUi(os.path.join("ui", "main.ui"), self)

        self.db_path = None
        self.dbconn = None
        self.engine = None
        self.highestImageID = None

        self.curImageID = None
        self.restrictedIDs = []
        self.image = None
        self.movie = None
        self.movie_aspect = None
        self.timer = None

        self.tagModel = None

        self.cache = {}

        self.allImagesView.setAcceptDrops(False) # Doesn't work if only set in Qt Designer 
        self.allImagesView.setDragEnabled(False) # ¯\_(ツ)_/¯

        self.allImagesView.installEventFilter(self)

        self.allImagesView.itemClicked.connect(self.thumbSelected)

        # connections
        
        self.actionNew_database.triggered.connect(self.newDatabase)

        self.actionLoad_database.triggered.connect(self.loadDatabase)

        self.actionImport.triggered.connect(self.importFiles)

        self.actionAdd_tag.triggered.connect(self.newTag)

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

    def exitCandle(self):
        sys.exit()

    ### DB Functions

    def newDatabase(self):
        path, _ = QFileDialog.getSaveFileName(self,"QFileDialog.getSaveFileName()","","SQLite3 (*.db);;All Files (*)")
        self.engine = create_engine(fr"sqlite:///{path}")

        Base.metadata.create_all(self.engine)

        session = sessionmaker(bind=self.engine)
        self.dbconn = session()

        logger.info("Database connected")

        self.getImageIDBounds()

        self.cache.clear()
        self.refreshTags()
        self.refreshImages()

    def loadDatabase(self):
        path, _ = QFileDialog.getOpenFileName(self)

        self.db_path = path

        self.engine = create_engine(fr"sqlite:///{path}")

        session = sessionmaker(bind=self.engine)
        self.dbconn = session()

        logger.info("Database connected")

        self.getImageIDBounds()

        self.cache.clear()
        self.refreshTags()
        self.refreshImages()
        

    def autoLoadDB(self):
        self.engine = create_engine(r"sqlite:///test.db")

        session = sessionmaker(bind=self.engine)
        self.dbconn = session()

        logger.info("Database connected")

        self.getImageIDBounds()

        self.cache.clear()
        self.refreshTags()
        self.refreshImages()

    def getImageIDBounds(self):
        max_id = self.dbconn.query(func.max(Files.id)).first()
        self.highestImageID = max_id[0]

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
        self.cache.clear()
        self.refreshImages()

    ### Tag Functions

    def refreshTags(self):
        all_tags = self.dbconn.query(Tags)
        
        self.tagModel = QtGui.QStandardItemModel(self.tagList)
        self.tagList.setModel(self.tagModel)

        for tag in all_tags:
            tag_item = QtGui.QStandardItem(tag.name)
            tag_item.setCheckable(True)
            self.tagModel.appendRow(tag_item)

        self.tagModel.itemChanged.connect(self.onTagChanged)

    def onTagChanged(self, item):
        if self.tagEditCheck.checkState() == Qt.Checked:
            selected_images = self.allImagesView.selectedItems()

            tag_id = self.dbconn.query(Tags.id).filter(Tags.name == item.text()).one()

            selected_images_names = [image.text() for image in selected_images]

            if item.checkState() == 2: 
                all_fileids = self.dbconn.query(Files.id).filter(Files.name.in_(selected_images_names))

                self.engine.execute(FileTags.__table__.insert(),
                        [dict(tagid=tag_id[0], fileid=id[0]) for id in all_fileids]
                    )
            elif item.checkState() == 0:
                all_fileids = self.dbconn.query(Files.id).filter(Files.name.in_([image.text() for image in selected_images]))
                self.dbconn.query(FileTags).filter(and_(FileTags.fileid.in_(all_fileids), FileTags.tagid == tag_id[0])).delete(synchronize_session='fetch')
                self.dbconn.commit()
        else:
            num_checked = 0
            tags = []
            for index in range(self.tagModel.rowCount()):
                item = self.tagModel.item(index)
                if item.checkState() == Qt.Checked:
                    num_checked += 1
                    tags.append(item.text())
            
            if num_checked == 0:
                self.refreshImages()
                self.restrictedIDs.clear()
            else:
                self.refreshImagesWTags(tags)

    def thumbSelected(self, item):
        if self.tagEditCheck.isChecked():
            try:
                master_item = (self.allImagesView.selectedItems())[0]
            except IndexError:
                return
            
            master_id = self.dbconn.query(Files.id).filter(Files.name == master_item.text()).one()
            all_tagids = self.dbconn.query(FileTags.tagid).filter(FileTags.fileid == master_id[0])
            all_tags = self.dbconn.query(Tags.name).filter(Tags.id.in_(all_tagids))

            matching_tags = []

            for tag in all_tags:
                lv_item = (self.tagModel.findItems(tag[0], Qt.MatchExactly))[0]
                lv_item.setCheckState(True)
                matching_tags.append(lv_item)

            for index in range(self.tagModel.rowCount()):
                lv_item = self.tagModel.item(index)
                if lv_item not in matching_tags:
                    lv_item.setCheckState(False)
        else:
            pass

    def newTag(self):
        popup = QtWidgets.QInputDialog.getText(self, "New Tag", "Enter tag name")
        if popup[1] == True:
            query = Tags.insert().values(
                name = popup[0]
            )
            self.dbconn.execute(query)

            self.refreshTags()

    ### Image Functions

    def refreshImages(self):
        self.allImagesView.clear()
        if "all_files_data" in self.cache:
            for image in self.cache["all_files_data"].values():
                item = QListWidgetItem(image[0], image[1])
                self.allImagesView.addItem(item)
        else:        
            all_files = self.dbconn.query(Files)

            ## only load images in view +- 10 or so

            self.cache["all_files_data"] = {}

            for file in all_files:
                path = file.path
                name = file.name
                icon = QtGui.QIcon(path)
                item = QListWidgetItem(icon, name)
                self.allImagesView.addItem(item)
                self.cache["all_files_data"][name] = (icon, name)

        

    def refreshImagesWTags(self, tags):
        self.allImagesView.clear()

        all_tags = self.dbconn.query(Tags.id).filter(Tags.name.in_(tags))
        all_filetags = self.dbconn.query(FileTags.fileid).filter(FileTags.tagid.in_(all_tags))
        all_files = self.dbconn.query(Files).filter(Files.id.in_(all_filetags))

        if self.cache["all_files_data"]:        
            for file in all_files:
                name = file.name
                image = self.cache["all_files_data"][name]
                item = QListWidgetItem(image[0], image[1])
                self.allImagesView.addItem(item)
                self.restrictedIDs.append(file.id)


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
        file_data = self.dbconn.query(Files).filter(Files.name == item.text()).one()
        self.loadImage(file_data)

    def nextImage(self):
        if self.curImageID + 1 > self.highestImageID:
            pass
        elif self.curImageID and self.restrictedIDs:
            try:
                index = self.restrictedIDs.index(self.curImageID)
                try:
                    file_data = self.getImageByID(self.restrictedIDs[index + 1])
                except IndexError:
                    return
                self.loadImage(file_data)
            except ValueError:
                file_data = self.getImageByID(self.restrictedIDs[0])
                self.loadImage(file_data)
        elif self.curImageID:
            i = 1
            while True:
                file_data = self.getImageByID(self.curImageID + i)
                if file_data:
                    break
                else:
                    i += 1

            self.loadImage(file_data)


    def prevImage(self):
        if self.curImageID - 1 <= 0:
            pass
        elif self.curImageID and self.restrictedIDs:
            try:
                index = self.restrictedIDs.index(self.curImageID)
                try:
                    file_data = self.getImageByID(self.restrictedIDs[index - 1])
                except IndexError:
                    return
                self.loadImage(file_data)
            except ValueError:
                file_data = self.getImageByID(self.restrictedIDs[0])
                self.loadImage(file_data)
        elif self.curImageID:
            i = -1
            while True:
                file_data = self.getImageByID(self.curImageID + i)
                if file_data:
                    break
                else:
                    i -= 1

            self.loadImage(file_data)

    def getImageByID(self, id):
        file_data = self.dbconn.query(Files).filter(Files.id == id).first()

        return file_data

    def loadImage(self, file_data):
        path = file_data.path

        image_reader = QtGui.QImageReader(path)

        if image_reader.supportsAnimation() and image_reader.imageCount() > 1:
            self.movie = QMovie(path)

            self.movie.jumpToFrame(0)

            size = self.movie.currentImage().size()

            self.movie_aspect = size.width() / size.height()  

            width = self.singleImageView.height() * self.movie_aspect
            if width <= self.singleImageView.width():
                size = QtCore.QSize(width, self.singleImageView.height())
            else:
                height = self.singleImageView.width() / self.movie_aspect
                size = QtCore.QSize(self.singleImageView.width(), height)

            self.movie.setScaledSize(size)

            self.singleImageView.setMovie(self.movie)

            self.movie.start()

            self.image = None
        else:
            self.image = QtGui.QPixmap(path)

            if self.image.isNull():
                QtWidgets.QMessageBox.information(self, "Image Viewer", "Cannot load %s." % file_data[1])
                return

            self.singleImageView.setPixmap(self.image.scaled(self.singleImageView.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

            self.movie = None

        self.curImageID = file_data.id
        self.stackedWidget.setCurrentIndex(0)
    
    def resizeEvent(self, event):
        if event.spontaneous() and self.image:
            self.singleImageView.setPixmap(self.image.scaled(self.singleImageView.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        elif event.spontaneous() and self.movie:
            width = self.singleImageView.height() * self.movie_aspect
            if width <= self.singleImageView.width():
                size = QtCore.QSize(width, self.singleImageView.height())
            else:
                height = self.singleImageView.width() / self.movie_aspect
                size = QtCore.QSize(self.singleImageView.width(), height)

            self.movie.setScaledSize(size)