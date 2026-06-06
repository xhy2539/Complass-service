"""RAG 检索服务入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import HTTPException

from .indexer import add_case
from .indexer import rebuild
from .models import IndexRequest
from .models import RebuildResponse
from .models import RetrievedCaseResult
from .models import SearchRequest
from .models import SearchResponse
from .reranker import rerank
from .retriever import hybrid_search


@asynccontextmanager
async def lifespan(app: FastAPI):
    from pathlib import Path

    faiss_path = Path(__file__).resolve().parent.parent / "storage" / "faiss.index"
    if not faiss_path.exists():
        try:
            rebuild()
        except Exception:
            pass
    yield


app = FastAPI(title="Complass RAG Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    candidates = hybrid_search(
        query=req.query,
        review_module=req.review_module,
        contract_type=req.contract_type,
        review_role=req.review_role,
        n_candidates=10,
    )

    if not candidates:
        return SearchResponse(results=[])

    ranked = rerank(
        query=req.query,
        candidates=candidates,
        top_k=req.top_k,
    )

    results = [_to_result(c, i, len(ranked)) for i, c in enumerate(ranked)]
    return SearchResponse(results=results)


@app.post("/index")
def index_case(req: IndexRequest):
    try:
        add_case(req.case)
        return {"detail": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/rebuild", response_model=RebuildResponse)
def rebuild_index():
    try:
        info = rebuild()
        return RebuildResponse(**info)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _to_result(case: dict, rank: int, total: int) -> RetrievedCaseResult:
    score = 1.0 - rank / max(total, 10)
    return RetrievedCaseResult(
        case_id=case["case_id"],
        score=round(score, 4),
        contract_type=case.get("contract_type"),
        review_role=case.get("review_role"),
        review_module=case.get("review_module", ""),
        change_pattern=case.get("change_pattern", ""),
        before_example=case.get("before_example"),
        after_example=case.get("after_example"),
        diff_summary=case.get("diff_summary"),
        user_intent=case.get("user_intent"),
        risk_name=case.get("risk_name", ""),
        check_point=case.get("check_point", ""),
        trigger_condition=case.get("trigger_condition", ""),
        default_risk_level=case.get("default_risk_level"),
        suggestion_template=case.get("suggestion_template", ""),
        example_clause=case.get("example_clause"),
    )
