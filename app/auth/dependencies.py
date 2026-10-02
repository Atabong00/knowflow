from fastapi import Request, Depends, HTTPException, status
from itsdangerous import URLSafeTimedSerializer, URLSafeSerializer, BadSignature, SignatureExpired
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.auth.keycloak import keycloak_client
from app.models.user import User
from app.core.logging_config import log_auth_event, log_error

# Serializer to sign session cookies securely with timestamp
serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="session")
csrf_serializer = URLSafeSerializer(settings.SECRET_KEY, salt="csrf")

class AuthenticatedUser:
    """Convenience class to wrap token claims and mapped permissions."""
    def __init__(self, payload: dict):
        self.keycloak_id = payload.get("sub")
        self.username = payload.get("preferred_username")
        self.email = payload.get("email")
        self.name = payload.get("name") or self.username or "Employee"

        # Combine Realm Roles & Client Specific Roles
        realm_roles = payload.get("realm_access", {}).get("roles", [])
        client_roles = payload.get("resource_access", {}).get(settings.KEYCLOAK_CLIENT_ID, {}).get("roles", [])
        self.roles = list(set(realm_roles + client_roles))

        # Determine Primary UI Role
        if "Admin" in self.roles:
            self.primary_role = "Administrator"
        elif "Editor" in self.roles:
            self.primary_role = "Editor"
        else:
            self.primary_role = "Employee"

def get_session_data(request: Request, max_age: int = 28800) -> dict | None:
    """Retrieve and verify the secure session cookie with timestamp check."""
    session_cookie = request.cookies.get("session_token")
    if not session_cookie:
        return None
    try:
        return serializer.loads(session_cookie, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None

def generate_csrf_token() -> str:
    """Generate a new CSRF token."""
    return csrf_serializer.dumps("csrf")

def validate_csrf_token(request: Request, submitted_token: str | None = None):
    """Validate CSRF token by comparing the cookie with the submitted token.

    ``submitted_token`` is the token extracted from the ``X-CSRF-Token`` header
    (used by AJAX/fetch calls). If it is not provided, the header value is read
    from the request. Callers (such as the CSRF middleware) may read the token
    from the form body for regular HTML form submissions and pass it here.

    In all cases the token must match the signed token held in the
    ``csrf_token`` cookie (standard double-submit cookie pattern).
    """
    cookie_token = request.cookies.get("csrf_token")

    if submitted_token is None:
        submitted_token = request.headers.get("X-CSRF-Token")

    if not cookie_token or not submitted_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing"
        )

    if cookie_token != submitted_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token mismatch"
        )

    try:
        csrf_serializer.loads(cookie_token)
    except BadSignature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token"
        )


def sync_user_profile(db: Session, user: AuthenticatedUser):
    """Sync Keycloak user profile to local database cache."""
    db_user = db.query(User).filter(User.keycloak_id == user.keycloak_id).first()
    if not db_user:
        db_user = User(
            keycloak_id=user.keycloak_id,
            display_name=user.name,
            email=user.email or f"{user.username}@company.local"
        )
        db.add(db_user)
        db.commit()
    elif db_user.display_name != user.name or db_user.email != user.email:
        db_user.display_name = user.name
        db_user.email = user.email or db_user.email
        db.commit()


async def get_current_user(request: Request, db: Session = Depends(get_db)) -> AuthenticatedUser | None:
    """
    Optional authentication dependency. Decodes token and refreshes expired tokens
    using the refresh token. Returns None if unauthenticated.
    User profile sync is handled at login time, not on every request.
    """
    session_data = get_session_data(request)
    if not session_data:
        return None

    access_token = session_data.get("access_token")
    refresh_token = session_data.get("refresh_token")
    if not access_token:
        return None

    try:
        payload = await keycloak_client.verify_token(access_token)
        user = AuthenticatedUser(payload)
        return user
    except Exception as access_error:
        log_error("Token verification failed", access_error)
        # Try to refresh the token if we have a refresh token
        if refresh_token:
            try:
                new_tokens = await keycloak_client.refresh_token(refresh_token)
                if new_tokens and new_tokens.get("access_token"):
                    # Update session data with new tokens
                    session_data["access_token"] = new_tokens.get("access_token")
                    if new_tokens.get("refresh_token"):
                        session_data["refresh_token"] = new_tokens.get("refresh_token")
                    if new_tokens.get("id_token"):
                        session_data["id_token"] = new_tokens.get("id_token")
                    
                    # Store refreshed session data in request state for middleware to pick up
                    request.state.refreshed_session = serializer.dumps(session_data)
                    
                    payload = await keycloak_client.verify_token(new_tokens["access_token"])
                    user = AuthenticatedUser(payload)
                    return user
            except Exception as refresh_error:
                log_error("Token refresh failed", refresh_error)
                pass
        
        # Invalid/Expired token and refresh failed
        return None

async def require_user(request: Request, db: Session = Depends(get_db)) -> AuthenticatedUser:
    """
    Enforces authentication. Redirects HTML requests to /login,
    and raises 401 Unauthorized for API/AJAX requests.
    """
    user = await get_current_user(request, db)
    if not user:
        accept_header = request.headers.get("accept", "")
        if "text/html" in accept_header:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/login"}
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid. Please log in again."
        )
    return user

class RoleRequirement:
    """Enforces specific Keycloak roles (e.g. Admin, Editor)."""
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: AuthenticatedUser = Depends(require_user)) -> AuthenticatedUser:
        # Check if the user's Keycloak roles intersection exists with allowed roles
        has_role = any(role in user.roles for role in self.allowed_roles)
        if not has_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. You do not have permissions to perform this operation."
            )
        return user
