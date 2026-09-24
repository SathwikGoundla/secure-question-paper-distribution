"""
Aggregates every API v1 sub-router into a single router mounted by
main.py under settings.API_V1_PREFIX (default "/api/v1").
"""

from fastapi import APIRouter

from app.api.v1 import admin, audit, auth, exam_session, health, papers

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(papers.router)
api_router.include_router(exam_session.router)
api_router.include_router(admin.router)
api_router.include_router(audit.router)
