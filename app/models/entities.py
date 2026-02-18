from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Show(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title_input: str
    title_canonical: str
    bangumi_id: Optional[int] = None
    status: str = "planned"  # planned|airing|finished
    total_eps: Optional[int] = None
    ep_offset: int = Field(default=0)  # absolute-to-season offset: season_ep = absolute_ep - ep_offset
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Episode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    show_id: int = Field(index=True)
    ep_no: int
    air_datetime: Optional[datetime] = None
    state: str = "planned"  # planned|aired|downloaded|missing


class ShowAlias(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    show_id: int = Field(index=True)
    alias: str = Field(index=True)


class ShowProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    show_id: int = Field(index=True, unique=True)
    preferred_subgroups: Optional[str] = None
    min_score: int = 70


class Release(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    show_id: int = Field(index=True)
    ep_no: int
    source: str
    title: str
    magnet_or_torrent: str
    quality: Optional[str] = None
    subgroup: Optional[str] = None
    score: int = 0
    state: str = "queued"  # queued|downloading|completed
    created_at: datetime = Field(default_factory=datetime.utcnow)
