from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .core.config import settings
from .api.dependencies import get_current_admin
from .api.routes import search, results, proxy, dashboard, comments, auth
from .core.database import engine, Base
from .core.logging_config import setup_logging
from .core.startup_migrations import run_startup_migrations
from .models.admin import AdminUser
from .core.security import get_password_hash
from .core.database import SessionLocal

# Setup logging
setup_logging()

def init_admin():
    db = SessionLocal()
    try:
        user = db.query(AdminUser).filter(AdminUser.username == "admin").first()
        if not user:
            user = AdminUser(
                username="admin", 
                hashed_password=get_password_hash("admin")
            )
            db.add(user)
            db.commit()
    finally:
        db.close()

# Create database tables
Base.metadata.create_all(bind=engine)
run_startup_migrations()
init_admin()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
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
app.include_router(search.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(get_current_admin)])
app.include_router(results.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(get_current_admin)])
app.include_router(proxy.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(get_current_admin)])
app.include_router(dashboard.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(get_current_admin)])
app.include_router(comments.router, prefix=settings.API_V1_PREFIX, dependencies=[Depends(get_current_admin)])


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
