import base64
import functools
import json
import logging
import os
from typing import Any, List, Tuple, Type
from boto3 import Session
from botocore.exceptions import (
    ClientError,
    ParamValidationError,
    NoCredentialsError,
    ParamValidationError,
    NoRegionError,
)
from pydantic.fields import FieldInfo
from pydantic import MySQLDsn, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    EnvSettingsSource,
)

from .constanst import Environment


@functools.lru_cache()
def get_secret() -> dict[str, Any] | None:
    try:
        session = Session()
        region = os.environ.get("AWS_DEFAULT_REGION")
        if not region:
            logging.error("AWS_DEFAULT_REGION environment variable is not set")
            return None

        client = session.client(service_name="secretsmanager", region_name=region)
        secret_id = os.environ.get("AWS_SECRET_ID")
        if not secret_id:
            logging.error("AWS_SECRET_ID environment variable is not set")
            return None

        response = client.get_secret_value(SecretId=secret_id)
        if "SecretString" in response:
            secret_dictionary = json.loads(response["SecretString"])
        else:
            secret_dictionary = json.loads(base64.b64decode(response["SecretBinary"]))
        return secret_dictionary
    except (
        ClientError,
        NoCredentialsError,
        ParamValidationError,
        NoRegionError,
    ) as error:
        if isinstance(error, (NoCredentialsError, ParamValidationError, NoRegionError)):
            logging.debug("AWS Secrets Manager: %s", error)
        else:
            message = f"{error.response['Error']['Code']} to secret"
            logging.error(f"{message} {secret_id}: {error}")
        return None


class SecretManagerSource(EnvSettingsSource):
    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> str | dict[str, Any]:
        environent = Environment(
            os.environ.get("ENVIRONMENT"),
        )
        if environent.is_local:
            field_value = os.environ.get(field_name, field.default)
            try:
                return json.loads(field_value)
            except json.JSONDecodeError:
                return field_value

        secret_dict = get_secret()
        if secret_dict is None:
            return field.default

        return secret_dict.get(field_name, field.default)


class AppSettings(BaseSettings):
    ENVIRONMENT: Environment

    JWT_ALG: str
    JWT_ACCESS_EXP: int
    JWT_REFRESH_EXP: int
    JWT_PUBLIC_KEY: SecretStr
    JWT_PRIVATE_KEY: SecretStr

    CORS_HEADERS: List[str]
    CORS_ORIGINS: List[str]

    DYNAMODB_TABLE_NAME: str

    MYSQL_USER: str
    MYSQL_PASSWORD: SecretStr
    MYSQL_HOST: str
    MYSQL_PORT: int
    MYSQL_DB: str

    @property
    def MYSQL_DSN(self) -> str:
        return str(
            MySQLDsn.build(
                scheme="mysql+aiomysql",
                username=self.MYSQL_USER,
                password=self.MYSQL_PASSWORD.get_secret_value(),
                host=self.MYSQL_HOST,
                port=self.MYSQL_PORT,
                path=self.MYSQL_DB,
            )
        )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.is_production

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.is_development

    @property
    def is_local(self) -> bool:
        return self.ENVIRONMENT.is_local

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (SecretManagerSource(settings_cls),)


settings = AppSettings()
get_secret.cache_clear()
