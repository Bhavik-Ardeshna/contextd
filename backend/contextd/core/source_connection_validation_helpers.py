"""Validation helpers for source connection service."""

from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.context import ApiContext
from contextd.platform.configs._base import ConfigValues
from contextd.platform.configs.auth import AuthConfig
from contextd.platform.locator import resource_locator


class SourceConnectionValidationHelpersMixin:
    """Input validation helpers for source connection service operations."""

    @staticmethod
    def _as_mapping(value: Any) -> Dict[str, Any]:
        """Coerce config-like values into a dict."""
        from collections.abc import Mapping

        if value is None:
            return {}

        if isinstance(value, Mapping):
            return dict(value)

        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()

        if hasattr(value, "values"):
            values = value.values
            if isinstance(values, Mapping):
                return dict(values)
            return values

        if isinstance(value, list) and all(
            isinstance(item, dict) and "key" in item and "value" in item for item in value
        ):
            return {item["key"]: item["value"] for item in value}

        raise TypeError(f"config_fields must be mapping-like; got {type(value).__name__}")

    async def validate_auth_fields(
        self, db: AsyncSession, short_name: str, auth_fields: dict, ctx: ApiContext
    ) -> AuthConfig:
        """Validate authentication fields against source schema."""
        source = await crud.source.get_by_short_name(db, short_name=short_name)
        if not source:
            raise HTTPException(status_code=404, detail=f"Source '{short_name}' not found")

        if not source.auth_config_class:
            raise HTTPException(
                status_code=422,
                detail=f"Source {source.name} does not support direct auth",
            )

        try:
            auth_config_class = resource_locator.get_auth_config(source.auth_config_class)
            auth_config = auth_config_class(**auth_fields)
            return auth_config
        except HTTPException:
            raise
        except Exception as e:
            from pydantic import ValidationError

            if isinstance(e, ValidationError):
                errors = "; ".join([f"{err['loc'][0]}: {err['msg']}" for err in e.errors()])
                raise HTTPException(status_code=422, detail=f"Invalid auth fields: {errors}") from e
            raise HTTPException(status_code=422, detail=str(e)) from e

    async def validate_config_fields(  # noqa: C901
        self,
        db: AsyncSession,
        short_name: str,
        config_fields: Any,
        ctx: ApiContext,
    ) -> Dict[str, Any]:
        """Validate configuration fields against source schema, returning a plain dict.

        Also strips fields that have feature flags not enabled for the organization.
        """
        source = await crud.source.get_by_short_name(db, short_name=short_name)
        if not source:
            raise HTTPException(status_code=404, detail=f"Source '{short_name}' not found")

        if not config_fields:
            return {}

        if not source.config_class:
            try:
                return self._as_mapping(config_fields)
            except Exception:
                return {}

        try:
            payload = self._as_mapping(config_fields)
            config_class = resource_locator.get_config(source.config_class)
            enabled_features = ctx.organization.enabled_features or []

            for field_name, field_info in config_class.model_fields.items():
                json_schema_extra = field_info.json_schema_extra or {}
                feature_flag = json_schema_extra.get("feature_flag")

                if feature_flag and feature_flag not in enabled_features:
                    if field_name in payload and payload[field_name] is not None:
                        ctx.logger.warning(
                            f"Rejected config field '{field_name}' for {short_name}: "
                            f"feature flag '{feature_flag}' not enabled for organization"
                        )
                        field_title = field_info.title or field_name
                        raise HTTPException(
                            status_code=403,
                            detail=(
                                f"The '{field_title}' feature requires the '{feature_flag}' "
                                f"feature to be enabled for your organization. "
                                f"Please contact support to enable this feature."
                            ),
                        )

            if hasattr(config_class, "model_validate"):
                model = config_class.model_validate(payload)
            else:
                model = config_class(**payload)

            if hasattr(model, "model_dump"):
                return model.model_dump()
            if hasattr(model, "dict"):
                return model.dict()
            return dict(model) if isinstance(model, dict) else payload

        except HTTPException:
            raise
        except Exception as e:
            from pydantic import ValidationError

            if isinstance(e, ValidationError):

                def _loc(err):
                    loc = err.get("loc", [])
                    return ".".join(str(item) for item in loc) if loc else "<root>"

                errors = "; ".join([f"{_loc(err)}: {err.get('msg')}" for err in e.errors()])
                raise HTTPException(
                    status_code=422, detail=f"Invalid config fields: {errors}"
                ) from e
            raise HTTPException(status_code=422, detail=str(e)) from e

    async def validate_direct_auth(
        self,
        db: AsyncSession,
        source: schemas.Source,
        auth_fields: AuthConfig,
        config_fields: Optional[ConfigValues],
        ctx: ApiContext,
    ) -> Dict[str, Any]:
        """Validate direct authentication credentials."""
        try:
            source_cls = resource_locator.get_source(source)
            source_instance = await source_cls.create(auth_fields, config=config_fields)
            source_instance.set_logger(ctx.logger)

            if hasattr(source_instance, "validate"):
                is_valid = await source_instance.validate()
                if not is_valid:
                    raise HTTPException(
                        status_code=400, detail="Authentication credentials are invalid"
                    )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"No validate method found for {source.short_name}",
                )
            return {"valid": True, "source": source.short_name}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Validation failed: {str(e)}") from e

    async def validate_oauth_token(
        self,
        db: AsyncSession,
        source: schemas.Source,
        access_token: str,
        config_fields: Optional[ConfigValues],
        ctx: ApiContext,
        credentials: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validate OAuth access token."""
        try:
            source_cls = resource_locator.get_source(source)

            source_instance = await source_cls.create(
                access_token=access_token, config=config_fields
            )

            source_instance.set_logger(ctx.logger)

            if hasattr(source_instance, "validate"):
                is_valid = await source_instance.validate()
                if not is_valid:
                    raise HTTPException(status_code=400, detail="OAuth token is invalid")
            return {"valid": True, "source": source.short_name}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Token validation failed: {str(e)}") from e
