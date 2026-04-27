from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .routers import calendar_account_routes, calendar_event_routes, oauth_routes, \
    organization_routes, auth_routes, test_routes, employee_routes
from mangum import Mangum

app = FastAPI(title="skiode")

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://192.168.0.107:5173",
    "http://192.168.0.107:5174",
    "http://skiode-frontend.s3-website.ap-south-1.amazonaws.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/")
async def root():
    return {"message": "FastAPI working", "db_backend": settings.DB_BACKEND}


@app.get("/health")
async def health():
    return {"status": "ok", "db_backend": settings.DB_BACKEND}


handler = Mangum(app)
