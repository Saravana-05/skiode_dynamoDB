import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .core.config import settings
from .middleware.audit_log_middleware import AuditLogMiddleware
from .routers import calendar_account_routes, calendar_event_routes, oauth_routes, \
    organization_routes, auth_routes, test_routes, employee_routes, datastore_routes, \
    audit_routes, query_builder_routes, user_interaction_routes
from mangum import Mangum

# ── Audit log setup ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(),                     # prints to terminal
        logging.FileHandler("audit.log", mode="a"),  # saves to file
    ]
)

app = FastAPI(title="skiode")

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://192.168.0.107:5173",
    "http://192.168.0.107:5174",
    "http://domainmodelconfig.s3-website-ap-southeast-2.amazonaws.com",
    "http://skiode-frontend.s3-website.ap-south-1.amazonaws.com",
    # Lambda Function URL (self — needed when frontend calls this Lambda directly)
    "https://bzpfusv4ugqui3ysdnx2j53iyy0kefvt.lambda-url.ap-south-1.on.aws",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.on\.aws",   # any Lambda URL
    allow_credentials=False,                      # must be False when allow_origins includes *
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

app.add_middleware(AuditLogMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


@app.on_event("startup")
async def startup():
    print(f"Starting FastAPI app... [backend: {settings.DB_BACKEND}]")
    if settings.DB_BACKEND == "dynamodb":
        from .core.dynamodb import init_dynamodb
        await init_dynamodb()
    else:
        from .core.database import init_pool
        await init_pool()


@app.on_event("shutdown")
async def shutdown():
    if settings.DB_BACKEND == "dynamodb":
        from .core.dynamodb import close_dynamodb
        await close_dynamodb()
    else:
        from .core.database import close_pool
        await close_pool()


app.include_router(calendar_account_routes.router)
app.include_router(calendar_event_routes.router)
app.include_router(oauth_routes.router)
app.include_router(organization_routes.router)
app.include_router(auth_routes.router)
app.include_router(test_routes.router)
app.include_router(employee_routes.router)
app.include_router(datastore_routes.router)
app.include_router(audit_routes.router)
app.include_router(query_builder_routes.router)
app.include_router(user_interaction_routes.router)


@app.get("/")
async def root():
    return {"message": "FastAPI working", "db_backend": settings.DB_BACKEND}


@app.get("/health")
async def health():
    return {"status": "ok", "db_backend": settings.DB_BACKEND}


handler = Mangum(app)