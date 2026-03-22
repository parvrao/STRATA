"""
Analyses routes — CRUD for saved strategy analyses.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import Optional

from database import get_db
from models import Analysis, User, StageEnum, AnalysisTypeEnum
from schemas import (
    CreateAnalysisRequest, AnalysisResponse, AnalysisListResponse,
    UpdateAnalysisRequest, MessageResponse
)
from auth_utils import get_current_user, get_current_verified_user

router = APIRouter()


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=AnalysisResponse, status_code=201)
async def create_analysis(
    body: CreateAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
):
    analysis = Analysis(
        user_id=current_user.id,
        stage=body.stage,
        analysis_type=body.analysis_type,
        title=body.title,
        input_data=body.input_data,
        tags=body.tags or [],
        status="completed",
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    return analysis


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("/", response_model=AnalysisListResponse)
async def list_analyses(
    stage: Optional[StageEnum] = None,
    analysis_type: Optional[AnalysisTypeEnum] = None,
    is_starred: Optional[bool] = None,
    search: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = [Analysis.user_id == current_user.id]
    if stage:
        filters.append(Analysis.stage == stage)
    if analysis_type:
        filters.append(Analysis.analysis_type == analysis_type)
    if is_starred is not None:
        filters.append(Analysis.is_starred == is_starred)
    if search:
        filters.append(Analysis.title.ilike(f"%{search}%"))

    # Total count
    count_result = await db.execute(
        select(func.count()).where(and_(*filters))
    )
    total = count_result.scalar_one()

    # Items
    offset = (page - 1) * per_page
    result = await db.execute(
        select(Analysis)
        .where(and_(*filters))
        .order_by(Analysis.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    items = result.scalars().all()

    return AnalysisListResponse(
        total=total,
        page=page,
        per_page=per_page,
        pages=-(-total // per_page),  # ceiling division
        items=items,
    )


# ── Get one ───────────────────────────────────────────────────────────────────

@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .where(Analysis.user_id == current_user.id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


# ── Update ────────────────────────────────────────────────────────────────────

@router.patch("/{analysis_id}", response_model=AnalysisResponse)
async def update_analysis(
    analysis_id: str,
    body: UpdateAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .where(Analysis.user_id == current_user.id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    if body.title is not None:
        analysis.title = body.title
    if body.is_starred is not None:
        analysis.is_starred = body.is_starred
    if body.tags is not None:
        analysis.tags = body.tags

    await db.commit()
    await db.refresh(analysis)
    return analysis


# ── Star / Unstar ─────────────────────────────────────────────────────────────

@router.post("/{analysis_id}/star", response_model=AnalysisResponse)
async def toggle_star(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .where(Analysis.user_id == current_user.id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    analysis.is_starred = not analysis.is_starred
    await db.commit()
    await db.refresh(analysis)
    return analysis


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{analysis_id}", response_model=MessageResponse)
async def delete_analysis(
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Analysis)
        .where(Analysis.id == analysis_id)
        .where(Analysis.user_id == current_user.id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    await db.delete(analysis)
    await db.commit()
    return MessageResponse(message="Analysis deleted")


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats/summary")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Usage summary for the user dashboard."""
    result = await db.execute(
        select(
            Analysis.stage,
            Analysis.analysis_type,
            func.count().label("count")
        )
        .where(Analysis.user_id == current_user.id)
        .group_by(Analysis.stage, Analysis.analysis_type)
    )
    rows = result.all()

    total = sum(r.count for r in rows)
    by_stage = {}
    by_type = {}
    for row in rows:
        by_stage[row.stage.value] = by_stage.get(row.stage.value, 0) + row.count
        by_type[row.analysis_type.value] = by_type.get(row.analysis_type.value, 0) + row.count

    # Recent analyses
    recent_result = await db.execute(
        select(Analysis)
        .where(Analysis.user_id == current_user.id)
        .order_by(Analysis.created_at.desc())
        .limit(5)
    )
    recent = recent_result.scalars().all()

    return {
        "total_analyses": total,
        "by_stage": by_stage,
        "by_type": by_type,
        "tokens_used_month": current_user.tokens_used_month,
        "recent": [AnalysisResponse.model_validate(a) for a in recent],
    }
