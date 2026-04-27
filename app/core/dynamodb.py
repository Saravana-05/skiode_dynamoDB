import aioboto3
from .config import settings

_dynamodb_context = None
_dynamodb = None


async def init_dynamodb():
    global _dynamodb_context, _dynamodb

    kwargs = {"region_name": settings.AWS_REGION}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if settings.DYNAMODB_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.DYNAMODB_ENDPOINT_URL

    session = aioboto3.Session()
    _dynamodb_context = session.resource("dynamodb", **kwargs)
    _dynamodb = await _dynamodb_context.__aenter__()
    print("DynamoDB connected.")


async def close_dynamodb():
    global _dynamodb_context, _dynamodb
    if _dynamodb_context:
        await _dynamodb_context.__aexit__(None, None, None)
    _dynamodb_context = None
    _dynamodb = None


def get_dynamodb():
    if _dynamodb is None:
        raise RuntimeError("DynamoDB not initialized. Did you forget to call init_dynamodb()?")
    return _dynamodb
