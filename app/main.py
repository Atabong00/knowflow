from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
from app.auth.dependencies import get_current_user, AuthenticatedUser, generate_csrf_token, validate_csrf_token
from app.routes import auth, dashboard, documents, categories, search, admin, training
from app.core.logging_config import log_request, log_error
from app.services.seed import seed_training_data

from app.core.database import engine, Base, SessionLocal
# Import models to register them on Base metadata
from app.models import User, Category, Document, AuditLog

# Ensure all database tables exist on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG
)

# Mount static files (stylesheets, javascript assets)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Initialize templates
templates = Jinja2Templates(directory="app/templates")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        log_request(request)
        response = await call_next(request)
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Set CSRF cookie for authenticated users on safe methods
        if request.method in ("GET", "HEAD", "OPTIONS"):
            response = await call_next(request)
            # Check if user is authenticated
            session_data = request.cookies.get("session_token")
            if session_data:
                csrf_cookie = request.cookies.get("csrf_token")
                if not csrf_cookie:
                    token = generate_csrf_token()
                    response.set_cookie(
                        "csrf_token",
                        token,
                        httponly=False,
                        max_age=3600 * 8,
                        samesite="lax",
                        secure=not settings.DEBUG
                    )
            
            # Update session cookie if tokens were refreshed during request
            if hasattr(request.state, "refreshed_session"):
                response.set_cookie(
                    "session_token",
                    request.state.refreshed_session,
                    httponly=True,
                    max_age=3600 * 8,
                    samesite="lax",
                    secure=not settings.DEBUG
                )
            return response
        
        # Validate CSRF on state-changing methods
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            # Eagerly read & cache the body so _CachedRequest replays it for the
            # downstream route (calling .form() alone does not cache the body).
            await request.body()
            submitted_token = request.headers.get("X-CSRF-Token")
            # Regular HTML form POSTs carry the token as a hidden field, which
            # cannot be sent as a header. Read it from the form body as a
            # fallback. Guard on content-type so JSON bodies aren't parsed.
            if not submitted_token:
                content_type = request.headers.get("content-type", "")
                if ("application/x-www-form-urlencoded" in content_type
                        or "multipart/form-data" in content_type):
                    form = await request.form()
                    submitted_token = form.get("csrf_token")
            try:
                validate_csrf_token(request, submitted_token)
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail}
                )

        return await call_next(request)


app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CSRFMiddleware)


# Include Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(documents.router)
app.include_router(categories.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(training.router)

# Custom Error Page / Redirection Handler
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    # If the exception is a standard redirect instruction, proceed with standard redirection
    if exc.status_code in [status.HTTP_301_MOVED_PERMANENTLY, status.HTTP_302_FOUND, status.HTTP_303_SEE_OTHER, status.HTTP_307_TEMPORARY_REDIRECT]:
        return RedirectResponse(
            url=exc.headers.get("Location", "/login"), 
            status_code=exc.status_code
        )

    # For browser clients, serve custom glassmorphic error page
    accept_header = request.headers.get("accept", "")
    if "text/html" in accept_header:
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "request": request,
                "status_code": exc.status_code,
                "detail": exc.detail
            },
            status_code=exc.status_code
        )
    
    # Standard JSON fallback for API calls
    return JSONResponse(
        status_code=exc.status_code, 
        content={"detail": exc.detail}
    )

@app.get("/")
async def root(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    """Landing route. Redirects active sessions to dashboard, otherwise redirects to login portal."""
    if user:
        return RedirectResponse(url="/dashboard")
    return RedirectResponse(url="/login")

@app.get("/login")
async def login_landing(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    """SSO Landing portal."""
    if user:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request}
    )

@app.get("/health")
def health_check():
    """Liveness check probe."""
    return {"status": "healthy", "project": settings.PROJECT_NAME}


@app.on_event("startup")
def startup_seed():
    """Seed training data on startup if the database is available."""
    try:
        db = SessionLocal()
        try:
            seed_training_data(db)
        finally:
            db.close()
    except Exception as e:
        log_error("Training seed failed on startup", e)
