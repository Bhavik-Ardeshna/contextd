"""Dev auth endpoints for local email+password authentication."""

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from contextd import crud, schemas
from contextd.api.router import TrailingSlashRouter
from contextd.core.config import settings
from contextd.core.exceptions import NotFoundException
from contextd.core.logging import logger
from contextd.core.security import (
    create_dev_access_token,
    get_password_hash,
    verify_password,
)
from contextd.db.session import get_db
from contextd.models.user import User as UserModel

router = TrailingSlashRouter()


@router.post("/login", response_model=schemas.DevAuthToken)
async def dev_auth_login(
    login_data: schemas.DevAuthLogin,
    db: AsyncSession = Depends(get_db),
) -> schemas.DevAuthToken:
    """Login with email and password (dev mode only).

    Args:
        login_data: Email and password credentials.
        db: Database session.

    Returns:
        DevAuthToken with JWT access token.
    """
    if not settings.DEV_AUTH:
        raise HTTPException(status_code=404, detail="Not found")

    # Look up user by email
    try:
        user = await crud.user.get_by_email(db, email=login_data.email)
    except NotFoundException:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Get the DB model to check hashed_password
    db_user = await db.get(UserModel, user.id)
    if not db_user or not db_user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Verify password
    if not verify_password(login_data.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Create JWT token
    token = create_dev_access_token(
        data={"sub": str(user.id), "email": user.email}
    )

    logger.info(f"Dev auth login successful for {user.email}")

    return schemas.DevAuthToken(
        access_token=token,
        user_id=str(user.id),
        email=user.email,
    )


@router.post("/register", response_model=schemas.DevAuthToken)
async def dev_auth_register(
    register_data: schemas.DevAuthRegister,
    db: AsyncSession = Depends(get_db),
) -> schemas.DevAuthToken:
    """Register a new user with email and password (dev mode only).

    Args:
        register_data: Registration data (email, password, full_name).
        db: Database session.

    Returns:
        DevAuthToken with JWT access token.
    """
    if not settings.DEV_AUTH:
        raise HTTPException(status_code=404, detail="Not found")

    # Check if email is already taken
    try:
        existing = await crud.user.get_by_email(db, email=register_data.email)
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")
    except NotFoundException:
        pass  # Email not taken, good to proceed

    # Create user via existing CRUD (creates user + default org)
    user_in = schemas.UserCreate(
        email=register_data.email,
        full_name=register_data.full_name,
        password=register_data.password,
    )
    user_schema, org_schema = await crud.user.create_with_organization(db, obj_in=user_in)

    # Set hashed password on the DB model
    db_user = await db.get(UserModel, user_schema.id)
    if db_user:
        db_user.hashed_password = get_password_hash(register_data.password)
        db.add(db_user)
        await db.commit()

    # Create JWT token
    token = create_dev_access_token(
        data={"sub": str(user_schema.id), "email": user_schema.email}
    )

    logger.info(f"Dev auth registration successful for {user_schema.email}")

    return schemas.DevAuthToken(
        access_token=token,
        user_id=str(user_schema.id),
        email=user_schema.email,
    )
