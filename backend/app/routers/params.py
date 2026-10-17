"""Shared bounded id types: SQLite INTEGER tops out at 2**63-1, and larger values raise OverflowError (500)."""
from typing import Annotated

from fastapi import Path, Query
from pydantic import Field

MAX_ID = 2**63 - 1
Id = Annotated[int, Path(ge=1, le=MAX_ID)]
IdQuery = Annotated[int, Query(ge=1, le=MAX_ID)]
OptionalIdQuery = Annotated[int | None, Query(ge=1, le=MAX_ID)]
IdBody = Annotated[int, Field(ge=1, le=MAX_ID)]
