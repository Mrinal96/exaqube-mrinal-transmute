"""Conversion API namespace. Semantic conversions are intentionally not implemented."""

from fastapi import APIRouter

router = APIRouter(prefix="/conversions", tags=["conversions"])

