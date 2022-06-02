from operator import and_
import sys
import os
import queue
from math import ceil
from collections import namedtuple
from PyQt5 import QtGui, QtWidgets, QtCore, uic
from PyQt5.QtCore import Qt
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QImageIOHandler, QMovie
from PyQt5.QtWidgets import QFileDialog, QListWidgetItem
from logzero import logger
from sqlalchemy import create_engine, func, and_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from db import Base
from alchemy import Tags, Files, FileTags

preview = namedtuple("preview", "id title image")

image_thumbs_queue = queue.Queue()

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
        self.zoom = 1

        self.movie = None
        self.movie_aspect = None
        self.timer = None

        self.thread_load = None
        self.worker = None

        self.placeholder_icon = QtGui.QIcon(os.path.join("ui", "placeholder.png"))

        self.tagModel = None

        self.cache = {}

        self.allImagesView.setAcceptDrops(False) # Doesn't work if only set in Qt Designer 
        self.allImagesView.setDragEnabled(False) # ¯\_(ツ)_/¯

        self.allImagesView.installEventFilter(self)

        self.allImagesView.itemClicked.connect(self.thumbSelected)

        self.singleImageView.wheelEvent = self.scrollingEvent

        # connections
        
        self.actionNew_database.triggered.connect(self.newDatabase)

        self.actionLoad_database.triggered.connect(self.loadDatabase)

        self.actionImport.triggered.connect(self.importFiles)

        self.actionAdd_tag.triggered.connect(self.newTag)

        self.actionZoom_In.triggered.connect(self.zoomIn)

        self.actionZoom_Out.triggered.connect(self.zoomOut)

        self.actionFit_to_Window.triggered.connect(self.resetZoom)

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
        if path:
            self.engine = create_engine(fr"sqlite:///{path}", connect_args={'check_same_thread': False})

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
        if path:
            self.db_path = path

            self.engine = create_engine(fr"sqlite:///{path}", connect_args={'check_same_thread': False})

            session = sessionmaker(bind=self.engine)
            self.dbconn = session()

            logger.info("Database connected")

            self.getImageIDBounds()

            self.cache.clear()
            self.refreshTags()
        self.refreshImages()
        

    def autoLoadDB(self):
        self.engine = create_engine(r"sqlite:///test.db", connect_args={'check_same_thread': False})

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
        for file in files[:]:
            if not os.path.isfile(file):
                files.remove(file)

        self.engine.execute(Files.__table__.insert(),
            [dict(name=(os.path.split(file))[1], path=file) for file in files]
        )

        self.getImageIDBounds()

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

    def increaseProgressBar(self, i):
        self.progressBar.setValue(i)

    def refreshImages(self):
        self.allImagesView.clear()
        if "all_files_data" in self.cache:
            for image in self.cache["all_files_data"].values():
                item = QListWidgetItem(image[0], image[1])
                self.allImagesView.addItem(item)
        else:        
            self.cache["all_files_data"] = {}
            all_files = self.dbconn.query(Files)

            self.cache["all_files_data"] = {}

            self.progressBar.setMaximum(all_files.count())
            
            self.worker = LoadImageThumbs(all_files, self.allImagesView, self.cache)
            self.worker.begin()
            self.worker.progress.connect(self.increaseProgressBar)


    def loadThumb(self):
        item = image_thumbs_queue.get()
        image = QListWidgetItem(item[0], item[1])
        print(item[1])
        self.allImagesView.addItem(image)
        self.cache["all_files_data"][item[1]] = item

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
            image_test = QtWidgets.QAction("test")

            menu.addAction(image_display)
            menu.addAction(image_delete)

            menu_click = menu.exec(event.globalPos()) 

            try:
                item = source.itemAt(event.pos())
            except Exception as e:
                print(f"No item selected {e}")

            if menu_click == image_display:
                self.loadSingleImage(item)
            if menu_click == image_delete:
                pass # remove image from db and display

            return True
        elif event.type() == QtCore.QEvent.MouseButtonDblClick:
            print("test")
            return True

        return super(Candle, self).eventFilter(source, event)
    
    def loadSingleImage(self, item):
        if item == None:
            pass
        else:
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
            try:
                self.loadImage(file_data)
            except TypeError:
                print("Error")



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

            try:
                self.loadImage(file_data)
            except TypeError:
                print("Error")

    def getImageByID(self, id):
        file_data = self.dbconn.query(Files).filter(Files.id == id).first()

        return file_data

    def loadImage(self, file_data):
        path = file_data.path

        image_reader = QtGui.QImageReader(path)

        self.curImageID = file_data.id
        self.stackedWidget.setCurrentIndex(0)

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

            scene = QtWidgets.QGraphicsScene()
            label = QtWidgets.QLabel()

            label.setMovie(self.movie)

            self.movie.start()

            scene.addWidget(label)

            self.singleImageView.setScene(scene)

            self.image = None
        else:
            self.image = QtGui.QPixmap(path)
            
            if self.image.isNull():
                QtWidgets.QMessageBox.information(self, "Image Viewer", "Cannot load %s." % file_data[1])
                return

            item = QtWidgets.QGraphicsPixmapItem(self.image)
            item.setTransformationMode(Qt.SmoothTransformation)
            scene = QtWidgets.QGraphicsScene()
            scene.addItem(item)

            self.singleImageView.setScene(scene)

            self.singleImageView.fitInView(self.singleImageView.sceneRect(), Qt.KeepAspectRatio)
            self.zoom = self.singleImageView.transform().m11()

            self.movie = None
    
    def resizeEvent(self, event):
        if event.spontaneous() and self.image:
            self.singleImageView.fitInView(self.singleImageView.sceneRect(), Qt.KeepAspectRatio)
            self.zoom = self.singleImageView.transform().m11()
        elif event.spontaneous() and self.movie:
            width = self.singleImageView.height() * self.movie_aspect
            if width <= self.singleImageView.width():
                size = QtCore.QSize(width, self.singleImageView.height())
            else:
                height = self.singleImageView.width() / self.movie_aspect
                size = QtCore.QSize(self.singleImageView.width(), height)

            self.movie.setScaledSize(size)

    def zoomIn(self):
        try:
            self.zoom = self.singleImageView.transform().m11() * 1.05
            self.singleImageView.setTransform(QtGui.QTransform().scale(self.zoom, self.zoom))
        except AttributeError:
            pass

    def zoomOut(self):
        try:
            self.zoom = self.singleImageView.transform().m11() / 1.05
            self.singleImageView.setTransform(QtGui.QTransform().scale(self.zoom, self.zoom))
        except AttributeError:
            pass

    def resetZoom(self):
        try:
            self.zoom = 1
            self.singleImageView.setTransform(QtGui.QTransform().scale(self.zoom, self.zoom))
        except AttributeError:
            pass
    
    def scrollingEvent(self, event):
        mouse = event.angleDelta().y()/120
        if mouse > 0:
            self.zoomIn()
        elif mouse < 0:
            self.zoomOut()

class LoadImageThumbs(QtCore.QThread):
    progress = pyqtSignal(int)
    def __init__(self, file_data, allImagesView, cache):
        QtCore.QThread.__init__(self)
        self.file_data = file_data
        self.allImagesView = allImagesView
        self.cache = cache
    def run(self):
        i = 1

        num_files = self.file_data.count()
        increment = ceil(100 / num_files)
        current_percentage = increment

        for file in self.file_data:
            path = file.path
            name = file.name
            image = QtGui.QImage(path)
            pix = QtGui.QPixmap.fromImage(image)
            icon = QtGui.QIcon(pix)
            item = (icon, name)
            image_thumbs_queue.put(item)

            item = image_thumbs_queue.get()
            image = QListWidgetItem(item[0], item[1])
            self.allImagesView.addItem(image)
            self.cache["all_files_data"][item[1]] = item
            self.progress.emit(i)
            i += 1

    def begin(self):
        self.start()
