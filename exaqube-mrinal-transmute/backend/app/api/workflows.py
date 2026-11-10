"""Workflow API namespace for the future persisted DAG endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/workflows", tags=["workflows"])

