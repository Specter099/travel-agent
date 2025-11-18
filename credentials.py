import boto3
import json
from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta
import logging

# Configure logging
logger = logging.getLogger(__name__)

class CredentialsManager:
    def __init__(self, role_arn: str, session_name: str = "agent-session", external_id: str = "ai-agent"):
        self.role_arn = role_arn
        self.session_name = session_name
        self.credentials = None
        self.external_id = external_id

        # Cache for secrets with expiration
        self.secret_cache: Dict[str, Tuple] = {}  # {secret_name: (secret_value, expiry_time)}
        self.cache_ttl_minutes = 30  # Cache secrets for 30 minutes
    
    def get_temporary_credentials(self) -> Dict:
        sts = boto3.client('sts')
        response = sts.assume_role(
            RoleArn=self.role_arn,
            RoleSessionName=self.session_name,
            ExternalId=self.external_id
        )
        self.credentials = response['Credentials']
        return self.credentials
    
    def get_secret(self, secret_name: str, region: str = 'us-east-1') -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        # Check cache first
        if secret_name in self.secret_cache:
            cached_value, expiry_time = self.secret_cache[secret_name]
            if datetime.now() < expiry_time:
                logger.debug(f"Using cached secret for '{secret_name}'")
                return cached_value
            else:
                logger.debug(f"Cache expired for '{secret_name}', refreshing...")
                del self.secret_cache[secret_name]

        # Get fresh credentials if needed
        if not self.credentials:
            self.get_temporary_credentials()

        try:
            client = boto3.client(
                'secretsmanager',
                region_name=region,
                aws_access_key_id=self.credentials['AccessKeyId'],
                aws_secret_access_key=self.credentials['SecretAccessKey'],
                aws_session_token=self.credentials['SessionToken']
            )

            response = client.get_secret_value(SecretId=secret_name)
            secret = json.loads(response['SecretString'])

            # Extract and validate secrets
            result = (
                secret.get('x_api_key'),
                secret.get('amadeus_api_key'),
                secret.get('amadeus_api_secret'),
                secret.get('langsmith_api_key')
            )

            # Validate that secrets are not empty
            if not all(result):
                logger.warning(f"Some secrets in '{secret_name}' are missing or empty")

            # Cache the result
            expiry_time = datetime.now() + timedelta(minutes=self.cache_ttl_minutes)
            self.secret_cache[secret_name] = (result, expiry_time)
            logger.info(f"Retrieved and cached secret '{secret_name}' (expires in {self.cache_ttl_minutes} minutes)")

            return result

        except Exception as e:
            logger.error(f"Failed to retrieve secret '{secret_name}': {str(e)}")
            raise
    
    def create_bedrock_client(self, region: str = 'us-east-1'):
        if not self.credentials:
            self.get_temporary_credentials()
        
        return boto3.client(
            'bedrock-runtime',
            region_name=region,
            aws_access_key_id=self.credentials['AccessKeyId'],
            aws_secret_access_key=self.credentials['SecretAccessKey'],
            aws_session_token=self.credentials['SessionToken']
        )
