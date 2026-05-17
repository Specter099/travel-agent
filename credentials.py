import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, NamedTuple, Optional

import boto3

logger = logging.getLogger(__name__)


# Refresh STS credentials this many seconds before their expiration.
_STS_REFRESH_LEEWAY = timedelta(minutes=5)


class APISecrets(NamedTuple):
    xai_api_key: str
    amadeus_api_key: str
    amadeus_api_secret: str
    langsmith_api_key: Optional[str]


class CredentialsManager:
    """Assume a role, fetch secrets, and refresh both on expiry.

    Why: previous version cached STS credentials forever, so anything running
    longer than the role's session duration would hit ExpiredToken errors. We
    also returned a positional tuple of secrets that was easy to misindex.
    """

    def __init__(
        self,
        role_arn: str,
        external_id: str,
        session_name: str = "travel-agent-session",
        cache_ttl_minutes: int = 30,
    ):
        if not role_arn:
            raise ValueError("role_arn is required")
        if not external_id:
            raise ValueError("external_id is required")

        self.role_arn = role_arn
        self.external_id = external_id
        self.session_name = session_name
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)

        self._credentials: Optional[Dict] = None
        self._sts = boto3.client("sts")
        self._secret_cache: Dict[str, tuple] = {}

    def _credentials_expired(self) -> bool:
        if not self._credentials:
            return True
        expiry = self._credentials.get("Expiration")
        if not expiry:
            return True
        return datetime.now(timezone.utc) >= expiry - _STS_REFRESH_LEEWAY

    def _ensure_credentials(self) -> Dict:
        if self._credentials_expired():
            logger.info("Refreshing STS credentials via AssumeRole")
            response = self._sts.assume_role(
                RoleArn=self.role_arn,
                RoleSessionName=self.session_name,
                ExternalId=self.external_id,
            )
            self._credentials = response["Credentials"]
        return self._credentials

    def _secretsmanager_client(self, region: str):
        creds = self._ensure_credentials()
        return boto3.client(
            "secretsmanager",
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )

    def get_secret(self, secret_name: str, region: str = "us-east-1") -> APISecrets:
        cached = self._secret_cache.get(secret_name)
        if cached:
            value, expiry = cached
            if datetime.now(timezone.utc) < expiry:
                return value
            del self._secret_cache[secret_name]

        client = self._secretsmanager_client(region)
        response = client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response["SecretString"])

        result = APISecrets(
            xai_api_key=secret.get("x_api_key"),
            amadeus_api_key=secret.get("amadeus_api_key"),
            amadeus_api_secret=secret.get("amadeus_api_secret"),
            langsmith_api_key=secret.get("langsmith_api_key"),
        )

        if not (
            result.xai_api_key and result.amadeus_api_key and result.amadeus_api_secret
        ):
            raise ValueError(
                f"Secret '{secret_name}' is missing one of: x_api_key, amadeus_api_key, amadeus_api_secret"
            )

        self._secret_cache[secret_name] = (
            result,
            datetime.now(timezone.utc) + self.cache_ttl,
        )
        logger.info("Cached secret '%s' for %s", secret_name, self.cache_ttl)
        return result

    def create_bedrock_client(self, region: str = "us-east-1"):
        creds = self._ensure_credentials()
        return boto3.client(
            "bedrock-runtime",
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
