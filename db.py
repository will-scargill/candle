from sqlalchemy import MetaData, Table, Column, String, Integer
from sqlalchemy.sql.schema import ForeignKey

meta = MetaData()

Tags = Table(
    "tags", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String)
)

Files = Table(
    "files", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String),
    Column("path", String, unique=True)
)

FileTags = Table(
    "filetags", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fileid", Integer, ForeignKey("files.id")),
    Column("tagid", Integer, ForeignKey("tags.id"))
)