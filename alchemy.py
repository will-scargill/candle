from sqlalchemy.orm import declarative_base
from sqlalchemy import MetaData, Table, Column, String, Integer
from sqlalchemy.sql.schema import ForeignKey

from db import Base

class Tags(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)

class Files(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    path = Column(String)

class FileTags(Base):
    __tablename__ = "filetags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fileid = Column(Integer, ForeignKey("files.id"))
    tagid = Column(Integer, ForeignKey("tags.id"))
