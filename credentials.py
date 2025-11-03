import boto3
import json
from typing import Dict

class CredentialsManager:
    def __init__(self, role_arn: str, session_name: str = "agent-session", external_id: str = "ai-agent"):
        self.role_arn = role_arn
        self.session_name = session_name
        self.credentials = None
        self.external_id = external_id
    
    def get_temporary_credentials(self) -> Dict:
        sts = boto3.client('sts')
        response = sts.assume_role(
            RoleArn=self.role_arn,
            RoleSessionName=self.session_name,
            ExternalId=self.external_id
        )
        self.credentials = response['Credentials']
        return self.credentials
    
    def get_secret(self, secret_name: str, region: str = 'us-east-1') -> str:
        if not self.credentials:
            self.get_temporary_credentials()
        
        client = boto3.client(
            'secretsmanager',
            region_name=region,
            aws_access_key_id=self.credentials['AccessKeyId'],
            aws_secret_access_key=self.credentials['SecretAccessKey'],
            aws_session_token=self.credentials['SessionToken']
        )
        
        response = client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response['SecretString'])
        return secret.get('api_key'), secret.get('api_secret')
    
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
