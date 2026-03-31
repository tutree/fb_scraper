from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .core.config import ensure_keywords_file_seeded, settings
from .api.dependencies import get_current_admin, require_admin
from .api.routes import search, results, proxy, dashboard, comments, auth, automation
from .core.database import engine, Base
from .core.logging_config import setup_logging
from .core.startup_migrations import run_startup_migrations
from .models.admin import AdminUser
from .core.security import get_password_hash
from .core.database import SessionLocal
from .services.background_jobs import start_scheduler, stop_scheduler

# Setup logging
setup_logging()

def init_admin():
    db = SessionLocal()
    try:
        for uname, role in [("admin", "admin"), ("user", "user")]:
            existing = db.query(AdminUser).filter(AdminUser.username == uname).first()
            if not existing:
                db.add(AdminUser(
                    username=uname,
                    hashed_password=get_password_hash(uname),
                    role=role,
                ))
            elif existing.role != role:
                existing.role = role
        db.commit()
    finally:
        db.close()

# Create database tables
Base.metadata.create_all(bind=engine)
run_startup_migrations()
ensure_keywords_file_seeded()
init_admin()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# CORS middleware - must be before routers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(search.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(require_admin)])
app.include_router(results.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(get_current_admin)])
app.include_router(proxy.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(require_admin)])
app.include_router(dashboard.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(get_current_admin)])
app.include_router(comments.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(get_current_admin)])
app.include_router(automation.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(require_admin)])


@app.get("/")
async def root():
    return {
        "message": "Math Tutor Scraper API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return JSONResponse(
        content={"status": "healthy"},
        status_code=200,
    )
