import time
import httpx
from jose import jwt, jwk
from jose.exceptions import JWTError, ExpiredSignatureError
from urllib.parse import quote
from app.core.config import settings
from app.core.logging_config import log_error

class KeycloakClient:
    def __init__(self):
        self.server_url = settings.KEYCLOAK_SERVER_URL.rstrip('/')
        self.backend_url = settings.KEYCLOAK_BACKEND_URL.rstrip('/')
        self.realm = settings.KEYCLOAK_REALM
        self.client_id = settings.KEYCLOAK_CLIENT_ID
        self.client_secret = settings.KEYCLOAK_CLIENT_SECRET

        # Public facing URL (for browser redirects & token issuer verification)
        self.base_url = f"{self.server_url}/realms/{self.realm}"
        self.auth_url = f"{self.base_url}/protocol/openid-connect/auth"
        self.logout_url = f"{self.base_url}/protocol/openid-connect/logout"

        # Internal container facing URL (for backchannel exchange)
        self.token_url = f"{self.backend_url}/realms/{self.realm}/protocol/openid-connect/token"
        self.certs_url = f"{self.backend_url}/realms/{self.realm}/protocol/openid-connect/certs"

        self.jwks = None
        self.jwks_last_fetched = 0

    def get_login_url(self, redirect_uri: str, state: str) -> str:
        """Generate Keycloak URL to redirect user for authentication."""
        return (
            f"{self.auth_url}?client_id={self.client_id}"
            f"&response_type=code"
            f"&redirect_uri={quote(redirect_uri, safe='')}"
            f"&scope=openid+profile+email"
            f"&state={state}"
            f"&prompt=login"
        )

    async def exchange_code_for_tokens(self, code: str, redirect_uri: str) -> dict:
        """Exchange Authorization Code for Access, ID, and Refresh tokens."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.token_url, data=data, timeout=10.0)
                if response.status_code != 200:
                    raise Exception(f"Failed to exchange code: {response.text}")
                return response.json()
            except httpx.TimeoutException:
                log_error("Token exchange timeout", None)
                raise Exception("Keycloak is temporarily unavailable. Please try again later.")
            except httpx.ConnectError:
                log_error("Token exchange connection error", None)
                raise Exception("Cannot connect to Keycloak. Please contact support.")

    async def refresh_token(self, refresh_token: str) -> dict:
        """Refresh an expired access token using the refresh token."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.token_url, data=data, timeout=10.0)
                if response.status_code != 200:
                    raise Exception(f"Failed to refresh token: {response.text}")
                return response.json()
            except httpx.TimeoutException:
                log_error("Token refresh timeout", None)
                raise Exception("Keycloak is temporarily unavailable. Please try again later.")
            except httpx.ConnectError:
                log_error("Token refresh connection error", None)
                raise Exception("Cannot connect to Keycloak. Please contact support.")

    async def get_jwks(self):
        """Fetch and cache Keycloak JSON Web Key Sets (JWKS) for signature validation."""
        now = time.time()
        # Cache certificates for 1 hour to prevent flooding Keycloak endpoints
        if not self.jwks or now - self.jwks_last_fetched > 3600:
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(self.certs_url, timeout=10.0)
                    if response.status_code == 200:
                        self.jwks = response.json()
                        self.jwks_last_fetched = now
                    else:
                        raise Exception(f"Failed to fetch JWKS: {response.text}")
                except httpx.TimeoutException:
                    log_error("Keycloak JWKS fetch timeout", None)
                    raise Exception("Keycloak is temporarily unavailable. Please try again later.")
                except httpx.ConnectError:
                    log_error("Keycloak JWKS fetch connection error", None)
                    raise Exception("Cannot connect to Keycloak. Please contact support.")
        return self.jwks

    async def verify_token(self, token: str) -> dict:
        """Decode and verify signature, audience, and issuer of the access token."""
        try:
            jwks = await self.get_jwks()
            headers = jwt.get_unverified_header(token)
            kid = headers.get("kid")
            if not kid:
                raise JWTError("Token header is missing 'kid'")

            # Find matching key from key sets
            key_data = None
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    key_data = key
                    break

            if not key_data:
                # Force refresh certs cache and retry
                self.jwks = None
                jwks = await self.get_jwks()
                for key in jwks.get("keys", []):
                    if key.get("kid") == kid:
                        key_data = key
                        break
                if not key_data:
                    raise JWTError("Public key kid not found in Keycloak certificates")

            public_key = jwk.construct(key_data)

            # verify JWT signature, issuer, and client-id audience
            payload = jwt.decode(
                token,
                public_key.to_pem(),
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.base_url
            )
            return payload
        except ExpiredSignatureError:
            raise JWTError("Token has expired")
        except JWTError as e:
            raise JWTError(f"Invalid token: {str(e)}")
        except Exception as e:
            log_error("Token verification failed", e)
            raise JWTError(f"Token verification failed: {str(e)}")

    def get_logout_url(self, redirect_uri: str, id_token: str = None) -> str:
        """Generate logout URL to terminate session in Keycloak."""
        url = f"{self.logout_url}?client_id={self.client_id}&post_logout_redirect_uri={quote(redirect_uri, safe='')}"
        if id_token:
            url += f"&id_token_hint={id_token}"
        return url

keycloak_client = KeycloakClient()
