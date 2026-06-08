"""FastAPI routes for framework job management."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from .types import Job, JobDetailsResponse, JobRescheduleResponse, JobStatsResponse


def create_jobs_router(
    *,
    get_service: Callable[..., Any],
    get_access_scope: Callable[[dict], tuple[list[str], bool]],
    get_audit_actor: Callable[..., Any],
    require_readonly: Callable[..., Any],
    require_user: Callable[..., Any],
    handle_service_error: Callable[[Exception], None],
    service_error_type: type[Exception] = Exception,
) -> APIRouter:
    router = APIRouter(prefix="/jobs", tags=["cpkit"])

    @router.get("/")
    async def list_jobs(
        claims: dict = Depends(require_readonly),
        service=Depends(get_service),
    ) -> list[Job]:
        groups, is_admin = get_access_scope(claims)
        try:
            return service.list_visible_jobs(groups, is_admin)
        except service_error_type as err:
            handle_service_error(err)

    @router.get("/stats", response_model=JobStatsResponse)
    async def get_job_stats(
        claims: dict = Depends(require_readonly),
        service=Depends(get_service),
    ) -> JobStatsResponse:
        groups, is_admin = get_access_scope(claims)
        try:
            return service.get_visible_job_stats(groups, is_admin)
        except service_error_type as err:
            handle_service_error(err)

    @router.get("/{job_id}")
    async def get_job(
        job_id: int,
        claims: dict = Depends(require_readonly),
        service=Depends(get_service),
    ) -> Job:
        groups, is_admin = get_access_scope(claims)
        try:
            job = service.get_job_for_user(job_id, groups, is_admin)
        except service_error_type as err:
            handle_service_error(err)

        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job '{job_id}' was not found.",
            )

        return job

    @router.get("/{job_id}/details", response_model=JobDetailsResponse)
    async def get_job_details(
        job_id: int,
        claims: dict = Depends(require_readonly),
        service=Depends(get_service),
    ) -> JobDetailsResponse:
        groups, is_admin = get_access_scope(claims)
        try:
            details = service.get_job_details_for_user(job_id, groups, is_admin)
        except service_error_type as err:
            handle_service_error(err)

        if details is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job '{job_id}' was not found.",
            )

        return JobDetailsResponse(**details)

    @router.post("/{job_id}/reschedule", response_model=JobRescheduleResponse)
    async def reschedule_job(
        job_id: int,
        claims: dict = Depends(require_user),
        actor_id: str = Depends(get_audit_actor),
        service=Depends(get_service),
    ) -> JobRescheduleResponse:
        groups, is_admin = get_access_scope(claims)
        try:
            new_job_id = service.enqueue_job_reschedule(
                job_id,
                groups,
                is_admin,
                actor_id,
            )
        except service_error_type as err:
            handle_service_error(err)

        return JobRescheduleResponse(job_id=new_job_id)

    return router
