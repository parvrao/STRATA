"""
AI routes — Google Gemini proxy (free tier).
Gemini 1.5 Flash: free, 15 req/min, 1M tokens/day.
Get key at: aistudio.google.com → Get API Key
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import json
import time
import logging

from database import get_db
from models import User, Analysis, UsageLog, PlanEnum
from schemas import (
    CustomerIntelRequest, ProductProfilerRequest,
    PositioningRequest, IntakeAnalysisRequest, AIResponse
)
from auth_utils import get_current_verified_user
from middleware.rate_limit import ai_limit
from config import settings

router = APIRouter()
logger = logging.getLogger("strata.ai")

# ── Plan token budgets ────────────────────────────────────────────────────────
PLAN_LIMITS = {
    PlanEnum.free:       settings.FREE_TIER_MONTHLY_TOKENS,
    PlanEnum.build:      settings.BUILD_TIER_MONTHLY_TOKENS,
    PlanEnum.fundraise:  settings.SCALE_TIER_MONTHLY_TOKENS,
    PlanEnum.growth:     settings.BUILD_TIER_MONTHLY_TOKENS,
    PlanEnum.scale_plus: settings.SCALE_TIER_MONTHLY_TOKENS,
    PlanEnum.enterprise: settings.SCALE_TIER_MONTHLY_TOKENS,
    PlanEnum.command:    999_999_999,
}

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)


def check_token_budget(user: User):
    limit = PLAN_LIMITS.get(user.plan, settings.FREE_TIER_MONTHLY_TOKENS)
    if user.tokens_used_month >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly token budget exhausted for your {user.plan.value} plan.",
        )


async def call_gemini(prompt: str, system: str = "") -> tuple[dict, int, int]:
    """
    Call Gemini API, parse JSON response.
    Returns (parsed_dict, tokens_used, latency_ms).
    """
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI not configured. Add GEMINI_API_KEY to your environment variables.",
        )

    model = settings.GEMINI_MODEL
    url = GEMINI_URL.format(model=model, key=settings.GEMINI_API_KEY)

    # Build contents — Gemini doesn't have a system role,
    # so we prepend system instructions to the first user message
    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    payload = {
        "contents": [{"role": "user", "parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": settings.GEMINI_MAX_TOKENS,
            "responseMimeType": "application/json",  # force JSON output
        },
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AI request timed out. Please retry.")
    except Exception as e:
        logger.error(f"Gemini connection error: {e}")
        raise HTTPException(status_code=503, detail="AI service unreachable. Please retry.")

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail="AI rate limit hit. Please wait a moment and retry.")
    if resp.status_code == 400:
        err = resp.json()
        raise HTTPException(status_code=400, detail=f"AI request error: {err.get('error', {}).get('message', 'Bad request')}")
    if not resp.is_success:
        logger.error(f"Gemini error {resp.status_code}: {resp.text[:200]}")
        raise HTTPException(status_code=502, detail="AI service returned an error. Please retry.")

    data = resp.json()

    # Extract text from Gemini response structure
    try:
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        logger.error(f"Unexpected Gemini response structure: {data}")
        raise HTTPException(status_code=500, detail="AI returned unexpected format. Please retry.")

    # Strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse AI JSON: {raw[:300]}")
        raise HTTPException(status_code=500, detail="AI returned malformed output. Please retry.")

    # Gemini returns token counts in usageMetadata
    usage = data.get("usageMetadata", {})
    tokens = usage.get("totalTokenCount", 500)  # fallback estimate

    return result, tokens, latency_ms


async def log_usage(db, user, endpoint, tokens, latency_ms, analysis_type=None, stage=None):
    user.tokens_used_month += tokens
    log = UsageLog(
        user_id=user.id,
        endpoint=endpoint,
        analysis_type=analysis_type,
        stage=stage,
        tokens_total=tokens,
        latency_ms=latency_ms,
        model=settings.GEMINI_MODEL,
    )
    db.add(log)


# ── Customer Intelligence ─────────────────────────────────────────────────────

@router.post("/customer-intel", response_model=AIResponse)
async def generate_customer_intel(
    body: CustomerIntelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
    _=Depends(ai_limit),
):
    check_token_budget(current_user)

    stage_ctx = {
        "startup":    "early-stage startup targeting innovators and early adopters",
        "growth":     "growth-stage company ($2M–$20M ARR) targeting early majority buyers in committee purchases",
        "enterprise": "enterprise / MNC with a 6.8-person decision committee",
    }

    extras = ""
    if body.arr:        extras += f"\nCurrent ARR: {body.arr}"
    if body.acv:        extras += f"\nAverage contract value: {body.acv}"
    if body.deal_size:  extras += f"\nDeal size: {body.deal_size}"
    if body.sales_cycle: extras += f"\nSales cycle: {body.sales_cycle}"

    system = "You are a world-class customer intelligence expert. Always respond with valid JSON only — no markdown, no explanation, no backticks."

    prompt = f"""Generate 3 distinct, realistic customer personas for a {stage_ctx.get(body.stage.value, 'business')}.

Product: {body.product_description}
Industry: {body.industry}
Price point: {body.price_point or 'not specified'}
Geography: {body.geography or 'Global'}
Target customer hint: {body.target_customer or 'not specified'}{extras}

Return this exact JSON structure:
{{
  "personas": [
    {{
      "name": "realistic full name",
      "emoji": "single emoji representing them",
      "age": "age range e.g. 28-36",
      "location": "city type + country",
      "income": "annual income range",
      "jobTitle": "specific job title",
      "company": "company type and size",
      "psychographic": "2 sentences about values and decision-making style",
      "painPoints": "top 2 pain points relevant to this product",
      "buyingTrigger": "the exact moment that makes them search for this — 1 sentence",
      "objection": "their single strongest hesitation",
      "adoptionCategory": "Innovator or Early Adopter or Early Majority or Late Majority",
      "lifecycleStage": "Awareness or Consideration or Decision or Retention or Advocacy",
      "behavioralTrait": "one sharp phrase"
    }}
  ],
  "segmentSummary": "2 sentences describing the overall customer segment",
  "segmentBars": [
    {{"label": "demographic dimension", "pct": 35, "note": "brief context"}}
  ],
  "lifecycleDetails": {{
    "Awareness": "what drives discovery",
    "Consideration": "what they evaluate",
    "Decision": "what makes them commit",
    "Retention": "what keeps them",
    "Advocacy": "what makes them refer"
  }}
}}"""

    result, tokens, latency_ms = await call_gemini(prompt, system)
    await log_usage(db, current_user, "/ai/customer-intel", tokens, latency_ms, "customer_intel", body.stage.value)

    analysis = Analysis(
        user_id=current_user.id,
        stage=body.stage,
        analysis_type="customer_intel",
        title=f"Customer Intelligence — {body.industry}",
        input_data=body.model_dump(),
        output_data=result,
        tokens_used=tokens,
    )
    db.add(analysis)
    await db.commit()

    return AIResponse(result=result, tokens_used=tokens, analysis_id=analysis.id)


# ── Product Profiler ──────────────────────────────────────────────────────────

@router.post("/product-profiler", response_model=AIResponse)
async def generate_product_profiler(
    body: ProductProfilerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
    _=Depends(ai_limit),
):
    check_token_budget(current_user)

    stage_buyer = {
        "startup":    "early-stage customer (urgency-driven, self-serve, price-sensitive)",
        "growth":     "growth-stage early majority buyer (needs whole product, ROI proof, integrations)",
        "enterprise": "enterprise buyer (compliance, security certs, SLA, integration depth, dedicated support)",
    }

    system = "You are a senior product strategist. Always respond with valid JSON only — no markdown, no explanation, no backticks."

    prompt = f"""Analyse this product against what its target customers actually need.

Product: {body.product_name}
Features: {body.features}
Description: {body.description}
Competitors: {body.competitors or 'not specified'}
Price tier: {body.price_tier or 'not specified'}
Target buyer: {stage_buyer.get(body.stage.value, 'business buyer')}
Compliance certs: {body.compliance_certs or 'N/A'}
Enterprise integrations: {body.integrations or 'N/A'}

Return this exact JSON:
{{
  "gaps": [
    {{
      "dimension": "one of: Core Functionality | UX/Simplicity | Integrations | Support/Onboarding | Compliance/Security | Pricing Value | Brand Trust",
      "score": 7,
      "severity": "critical or medium or good",
      "recommendation": "specific 1-sentence action to close this gap",
      "effort": "low or medium or high",
      "timeframe": "e.g. 2-4 weeks"
    }}
  ],
  "radarData": [
    {{"label": "short label", "yours": 60, "needed": 85}}
  ],
  "topRecommendation": "2 sentences on the single highest-impact improvement",
  "riskNote": "1 sentence on what happens if these gaps are not closed",
  "quickWins": ["action 1", "action 2", "action 3"]
}}

Include 5-7 gaps ordered by severity descending. Be specific and honest."""

    result, tokens, latency_ms = await call_gemini(prompt, system)
    await log_usage(db, current_user, "/ai/product-profiler", tokens, latency_ms, "product_profiler", body.stage.value)

    analysis = Analysis(
        user_id=current_user.id,
        stage=body.stage,
        analysis_type="product_profiler",
        title=f"Product Profiler — {body.product_name}",
        input_data=body.model_dump(),
        output_data=result,
        tokens_used=tokens,
    )
    db.add(analysis)
    await db.commit()

    return AIResponse(result=result, tokens_used=tokens, analysis_id=analysis.id)


# ── Positioning Suite ─────────────────────────────────────────────────────────

@router.post("/positioning", response_model=AIResponse)
async def generate_positioning(
    body: PositioningRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
    _=Depends(ai_limit),
):
    check_token_budget(current_user)

    system = "You are a world-class brand strategist. Always respond with valid JSON only — no markdown, no explanation, no backticks."

    prompt = f"""Build a complete positioning strategy.

Current positioning: {body.current_positioning}
Brand values: {body.brand_values}
Competitors: {body.competitors}
How they want customers to feel: {body.feel or 'not specified'}
Differentiation axis: {body.positioning_axis or 'not specified'}
Stage: {body.stage.value}

Return this exact JSON:
{{
  "whitespaceDots": [
    {{"name": "YOU", "x": 35, "y": 70, "isOurs": true, "size": 14}},
    {{"name": "Competitor A", "x": 70, "y": 60, "isOurs": false, "size": 18}}
  ],
  "axisX": {{"low": "Simple / Self-serve", "high": "Complex / Managed"}},
  "axisY": {{"low": "Low Intelligence", "high": "High Intelligence"}},
  "guardrailsDos": [
    "specific DO 1", "specific DO 2", "specific DO 3", "specific DO 4"
  ],
  "guardrailsDonts": [
    "specific DONT 1", "specific DONT 2", "specific DONT 3", "specific DONT 4"
  ],
  "canvas": {{
    "audience": {{"headline": "primary audience", "detail": "2 sentences"}},
    "message": {{"headline": "core message in 6 words", "detail": "2 sentences"}},
    "channels": {{"headline": "top 2-3 channels", "detail": "2 sentences"}},
    "timing": {{"headline": "timing trigger", "detail": "2 sentences"}}
  }},
  "brief": {{
    "statement": "sharp one-sentence positioning statement",
    "forWhom": "precise target customer",
    "againstWhat": "the alternative they compare you to",
    "keyDiff": "single most defensible differentiation",
    "brandVoice": "tone and language style in 2 sentences",
    "winCondition": "what winning looks like in 12 months"
  }},
  "riskFlags": ["positioning risk 1", "positioning risk 2"]
}}

Include 4-6 dots on the whitespace map. Mark YOUR brand with isOurs: true."""

    result, tokens, latency_ms = await call_gemini(prompt, system)
    await log_usage(db, current_user, "/ai/positioning", tokens, latency_ms, "positioning_suite", body.stage.value)

    analysis = Analysis(
        user_id=current_user.id,
        stage=body.stage,
        analysis_type="positioning_suite",
        title=f"Positioning Strategy — {body.stage.value.title()}",
        input_data=body.model_dump(),
        output_data=result,
        tokens_used=tokens,
    )
    db.add(analysis)
    await db.commit()

    return AIResponse(result=result, tokens_used=tokens, analysis_id=analysis.id)


# ── Intake Analysis ───────────────────────────────────────────────────────────

@router.post("/analyse", response_model=AIResponse)
async def run_intake_analysis(
    body: IntakeAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
    _=Depends(ai_limit),
):
    check_token_budget(current_user)

    system = "You are a senior strategy consultant. Always respond with valid JSON only — no markdown, no explanation."

    prompt = f"""Analyse this {body.stage.value}-stage business and produce a strategic brief.

Input: {json.dumps(body.data, indent=2)}

Return JSON with:
- findings: list of 3-5 key strategic findings
- primaryRecommendation: string with the top recommendation and rationale
- immediateActions: list of 3 actions ranked by impact
- riskFlags: list of 2-3 specific risks
- confidenceScore: number 1-10
- confidenceReason: why that score"""

    result, tokens, latency_ms = await call_gemini(prompt, system)
    await log_usage(db, current_user, "/ai/analyse", tokens, latency_ms, body.analysis_type.value, body.stage.value)

    analysis = Analysis(
        user_id=current_user.id,
        stage=body.stage,
        analysis_type=body.analysis_type,
        title=f"Analysis — {body.stage.value.title()}",
        input_data=body.data,
        output_data=result,
        tokens_used=tokens,
    )
    db.add(analysis)
    await db.commit()

    return AIResponse(result=result, tokens_used=tokens, analysis_id=analysis.id)


# ── StrategyGPT Chat ──────────────────────────────────────────────────────────

@router.post("/chat")
async def strategy_chat(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
    _=Depends(ai_limit),
):
    check_token_budget(current_user)

    stage = body.get("stage", "startup")
    message = body.get("message", "").strip()
    history = body.get("history", [])

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI not configured. Add GEMINI_API_KEY.")

    stage_persona = {
        "startup":    "You are StrategyGPT in Startup Mode — expert in PMF validation, customer discovery, JTBD, ICP definition, Bass diffusion, and early-stage GTM. Give specific, actionable answers. Reference Sean Ellis, Clayton Christensen, and Geoffrey Moore where relevant.",
        "growth":     "You are StrategyGPT in Growth Mode — expert in chasm crossing (Geoffrey Moore), CAC/LTV/NRR unit economics, segment sequencing, positioning defence, and Series A-B scaling. Always quote specific metric thresholds.",
        "enterprise": "You are StrategyGPT in Enterprise Mode — expert in BCG Matrix portfolio analysis, VRIO moat assessment, Porter's Five Forces, multi-market positioning, and board-level strategic briefs. Think at the portfolio and stakeholder level.",
    }

    system = stage_persona.get(stage, stage_persona["startup"])

    # Build conversation history as a single prompt
    history_text = ""
    for h in history[-8:]:
        role = "User" if h.get("role") == "user" else "Assistant"
        history_text += f"\n{role}: {h.get('content', '')}"

    full_prompt = f"{system}\n\nConversation so far:{history_text}\n\nUser: {message}\n\nAssistant:"

    url = GEMINI_URL.format(model=settings.GEMINI_MODEL, key=settings.GEMINI_API_KEY)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": full_prompt}]}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 600,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
        if not resp.is_success:
            raise HTTPException(status_code=502, detail="AI unavailable. Please retry.")
        data = resp.json()
        reply = data["candidates"][0]["content"]["parts"][0]["text"]
        tokens = data.get("usageMetadata", {}).get("totalTokenCount", 200)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail="Chat unavailable. Please retry.")

    await log_usage(db, current_user, "/ai/chat", tokens, 0, "chat", stage)
    await db.commit()

    return {"reply": reply, "tokens_used": tokens}


# ── Usage ─────────────────────────────────────────────────────────────────────

@router.get("/usage")
async def get_ai_usage(current_user: User = Depends(get_current_verified_user)):
    limit = PLAN_LIMITS.get(current_user.plan, settings.FREE_TIER_MONTHLY_TOKENS)
    return {
        "plan": current_user.plan.value,
        "provider": "Google Gemini",
        "model": settings.GEMINI_MODEL,
        "tokens_used_month": current_user.tokens_used_month,
        "tokens_limit_month": limit,
        "tokens_remaining": max(0, limit - current_user.tokens_used_month),
        "pct_used": round((current_user.tokens_used_month / limit) * 100, 1) if limit else 0,
    }
