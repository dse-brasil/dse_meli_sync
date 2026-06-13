import logging
import httpx
from fastapi import APIRouter, HTTPException, Query, status, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/meli/callback", status_code=status.HTTP_200_OK)
async def meli_oauth_callback(
    request: Request,
    code: str = Query(..., description="Authorization code returned by Mercado Livre"),
    db: AsyncSession = Depends(get_db)
):
    """
    Callback endpoint for Mercado Livre OAuth 2.0 flow.
    Exchanges the temporary code for access and refresh tokens.
    """
    logger.info("Received OAuth callback from Mercado Livre.")

    # Strip quotes that might be loaded literally by the docker-compose env_file parser
    client_id = settings.MELI_CLIENT_ID.strip("'\"") if settings.MELI_CLIENT_ID else ""
    client_secret = settings.MELI_CLIENT_SECRET.strip("'\"") if settings.MELI_CLIENT_SECRET else ""

    if not client_id or not client_secret:
        logger.error("OAuth configuration missing: MELI_CLIENT_ID or MELI_CLIENT_SECRET not configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth credentials are not configured on the server."
        )

    # Resolve redirect_uri dynamically based on the request URL
    # This automatically matches ngrok or staging domains (e.g. https://.../api/v1/auth/meli/callback)
    resolved_redirect_uri = str(request.url).split("?")[0]
    
    # If using ngrok or behind an HTTPS proxy/load balancer, force https scheme to avoid mismatch
    if "ngrok" in resolved_redirect_uri or request.headers.get("x-forwarded-proto") == "https":
        resolved_redirect_uri = resolved_redirect_uri.replace("http://", "https://")
        
    logger.info(f"Resolved dynamic redirect_uri: {resolved_redirect_uri}")

    # Mercado Livre Token Exchange endpoint
    url = "https://api.mercadolibre.com/oauth/token"
    
    # Payload requirements according to ML OAuth documentation
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": resolved_redirect_uri
    }

    # Dynamically resolve redirect_uri using host request header if needed, 
    # but ML requires exact match with the one registered in the Dev Panel.
    # We will log the request payload for developer convenience
    logger.info(f"Sending exchange request to Mercado Livre with client_id: {settings.MELI_CLIENT_ID}")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url, 
                data=payload, 
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15.0
            )
            
            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Mercado Livre token exchange rejected: {response.text}"
                )

            token_data = response.json()
            
            # The payload contains:
            # {
            #   "access_token": "APP_USR-...",
            #   "token_type": "bearer",
            #   "expires_in": 21600,
            #   "scope": "offline_access read write",
            #   "user_id": 123456789,
            #   "refresh_token": "TG-..."
            # }
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            user_id = token_data.get("user_id")

            logger.info(f"Successfully obtained OAuth credentials for Mercado Livre User ID: {user_id}")

            # Return success page/payload to developer
            return {
                "message": "Autenticacao concluida com sucesso!",
                "user_id": user_id,
                "scope": token_data.get("scope"),
                "expires_in": token_data.get("expires_in"),
                "status": "authenticated",
                "notice": "Em ambiente de producao, os tokens sao salvos criptografados no banco de dados."
            }

        except httpx.RequestError as req_err:
            logger.error(f"HTTP connection failed during OAuth exchange: {str(req_err)}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not reach Mercado Livre authorization server."
            )
