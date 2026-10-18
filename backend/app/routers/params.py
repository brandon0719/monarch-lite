"""Shared bounded types: ids (SQLite INTEGER tops out at 2**63-1, and larger values raise OverflowError, a 500) and dates (2000..2100)."""
import datetime as dt
from typing import Annotated

from fastapi import Path, Query
from pydantic import Field

MAX_ID = 2**63 - 1
Id = Annotated[int, Path(ge=1, le=MAX_ID)]
IdQuery = Annotated[int, Query(ge=1, le=MAX_ID)]
OptionalIdQuery = Annotated[int | None, Query(ge=1, le=MAX_ID)]
IdBody = Annotated[int, Field(ge=1, le=MAX_ID)]

MIN_DAY, MAX_DAY = dt.date(2000, 1, 1), dt.date(2100, 12, 31)
Day = Annotated[dt.date, Field(ge=MIN_DAY, le=MAX_DAY)]
