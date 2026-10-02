import secrets
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from app.core.config import settings
from app.auth.keycloak import keycloak_client
from app.auth.dependencies import serializer, get_session_data, get_current_user, AuthenticatedUser, sync_user_profile
from app.core.logging_config import log_auth_event, log_error

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.get("/login")
async def login(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    """Redirects the client browser to Keycloak for authentication."""
    if user:
        return RedirectResponse(url="/dashboard")

    state = secrets.token_urlsafe(16)
    callback_url = f"{request.base_url.scheme}://{request.base_url.netloc}/auth/callback"

    login_url = keycloak_client.get_login_url(callback_url, state)

    response = RedirectResponse(url=login_url)
    response.set_cookie(
        "oauth_state",
        state,
        httponly=True,
        max_age=3600,
        path="/",
        samesite="lax",
        secure=not settings.DEBUG
    )
    return response

@router.get("/callback")
async def auth_callback(request: Request, code: str, state: str):
    """Handles callback redirection from Keycloak. Verifies token and establishes session."""
    # Verify CSRF state token
    state_cookie = request.cookies.get("oauth_state")
    if not state_cookie or state_cookie != state:
        log_auth_event("callback", success=False)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="State mismatch error (anti-CSRF check failed)."
        )

    callback_url = f"{settings.APP_BASE_URL}/auth/callback"
    try:
        # Request access/ID tokens via backchannel POST request
        tokens = await keycloak_client.exchange_code_for_tokens(code, callback_url)
    except Exception as e:
        log_auth_event("token_exchange", success=False)
        log_error("Authorization code exchange failed", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Authorization code exchange failed: {str(e)}"
        )

    # Serialize active tokens into signed session structure
    session_data = {
        "access_token": tokens.get("access_token"),
        "id_token": tokens.get("id_token"),
        "refresh_token": tokens.get("refresh_token")
    }
    signed_session = serializer.dumps(session_data)

    # Sync user profile to local database cache at login time and determine role
    redirect_url = "/dashboard"
    try:
        payload = await keycloak_client.verify_token(tokens.get("access_token"))
        user = AuthenticatedUser(payload)
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            sync_user_profile(db, user)
        finally:
            db.close()
        
        # Role-based redirect after login
        log_auth_event("login", success=True, detail=f"User roles: {user.roles}, primary_role: {user.primary_role}")
        if user.primary_role == "Administrator":
            redirect_url = "/admin"
        elif user.primary_role == "Editor":
            redirect_url = "/documents"
        else:
            redirect_url = "/dashboard"
    except Exception as e:
        log_error("Role detection failed", e)
        pass

    response = RedirectResponse(url=redirect_url)
    response.set_cookie(
        "session_token",
        signed_session,
        httponly=True,
        max_age=3600 * 8,  # Session holds for 8 hours
        samesite="lax",
        secure=not settings.DEBUG
    )
    # Clear temp state cookie
    response.delete_cookie("oauth_state")
    
    log_auth_event("login", success=True)
    return response

@router.get("/logout")
def logout(request: Request):
    """Logs the user out locally and redirects to login page."""
    response = RedirectResponse(url="/login")
    response.delete_cookie("session_token")
    response.delete_cookie("oauth_state")
    response.delete_cookie("csrf_token")

    log_auth_event("logout", success=True)
    return response
