import requests
from jose import jwt, JWTError


def decode_okta_token(id_token: str, issuer: str, client_id: str):
    try:
        # 1. Get JWKS
        jwks_url = f"{issuer}/v1/keys"
        jwks = requests.get(jwks_url).json()

        # 2. Decode + verify
        payload = jwt.decode(
            id_token,
            jwks,
            audience=client_id,
            issuer=issuer,
            options={"verify_at_hash": False}
        )

        return payload

    except JWTError as e:
        raise Exception(f"Invalid Okta token: {str(e)}")
