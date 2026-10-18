from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status

from poker_bot_platform.api.models import (
    AccountResponse,
    AdminMatchResponse,
    AdminMatchSummaryResponse,
    BotDiagnosticsResponse,
    BotProfileRequest,
    BotProfileResponse,
    BotProfileUpdateRequest,
    BotTokenResponse,
    ChangePasswordRequest,
    JoinMatchRequest,
    LoginRequest,
    MatchCreateRequest,
    MatchPreviewResponse,
    MatchViewResponse,
    MyMatchResponse,
    PasswordResetResponse,
    PlayerActionRequest,
    PlayerTableStateResponse,
    RegisterRequest,
)
from poker_bot_platform.api.rate_limit import RateLimitExceeded, SlidingWindowLimiter
from poker_bot_platform.api.security import SameOriginGuard, client_key, too_many_attempts
from poker_bot_platform.auth.models import Account
from poker_bot_platform.auth.repository import AuthConflictError, AuthNotFoundError
from poker_bot_platform.auth.service import (
    AuthService,
    BotProfileService,
    BotVerificationError,
    InvalidCredentialsError,
    InvalidSessionError,
)
from poker_bot_platform.domain import Role
from poker_bot_platform.integration.matches import MatchCommandError, MatchNotFound, MatchService
from poker_bot_platform.integration.runtime import (
    GameplayAccessError,
    GameplayConflictError,
    GameplayNotFoundError,
    GameplayUnavailableError,
    MatchRuntime,
)


async def _translate[T](operation: Awaitable[T]) -> T:
    """Map service errors onto consistent HTTP responses."""

    try:
        return await operation
    except (MatchNotFound, GameplayNotFoundError, AuthNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GameplayAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except GameplayUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "2"},
        ) from exc
    except (
        MatchCommandError,
        GameplayConflictError,
        AuthConflictError,
        BotVerificationError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def create_api_router(
    *,
    auth: AuthService,
    bots: BotProfileService,
    matches: MatchService,
    runtime: MatchRuntime,
    allowed_origin: str,
    cookie_name: str = "poker_session",
    cookie_secure: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    same_origin = SameOriginGuard(allowed_origin)
    login_clients = SlidingWindowLimiter(max_attempts=30, window_seconds=60)
    login_failures = SlidingWindowLimiter(max_attempts=5, window_seconds=300)
    code_failures = SlidingWindowLimiter(max_attempts=20, window_seconds=300)
    mutation_guard = [Depends(same_origin)]

    async def current_account(
        session_token: Annotated[str | None, Cookie(alias=cookie_name)] = None,
    ) -> Account:
        try:
            return await auth.resolve_session(session_token)
        except InvalidSessionError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    async def current_admin(
        account: Annotated[Account, Depends(current_account)],
    ) -> Account:
        if account.role is not Role.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
        return account

    CurrentAccount = Annotated[Account, Depends(current_account)]
    CurrentAdmin = Annotated[Account, Depends(current_admin)]

    async def code_attempt[T](account: Account, operation: Awaitable[T]) -> T:
        try:
            code_failures.check(account.id)
        except RateLimitExceeded as exc:
            operation.close()  # type: ignore[attr-defined]
            raise too_many_attempts(exc) from exc
        try:
            return await _translate(operation)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                code_failures.record(account.id)
            raise

    # Accounts

    @router.post(
        "/auth/register",
        response_model=AccountResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=mutation_guard,
    )
    async def register(body: RegisterRequest) -> AccountResponse:
        try:
            account = await auth.register(body.email, body.password)
        except AuthConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="an account with that email already exists; sign in instead",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return AccountResponse.from_account(account)

    @router.post("/auth/login", response_model=AccountResponse, dependencies=mutation_guard)
    async def login(body: LoginRequest, request: Request, response: Response) -> AccountResponse:
        client = client_key(request)
        email_key = body.email.strip().casefold()
        try:
            login_clients.check(client)
            login_failures.check(email_key)
        except RateLimitExceeded as exc:
            raise too_many_attempts(exc) from exc
        login_clients.record(client)
        try:
            issued = await auth.login(body.email, body.password)
        except (ValueError, InvalidCredentialsError) as exc:
            login_failures.record(email_key)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid email or password",
            ) from exc
        login_failures.reset(email_key)
        max_age = max(0, int(auth.session_lifetime.total_seconds()))
        response.set_cookie(
            cookie_name,
            issued.token,
            max_age=max_age,
            expires=issued.expires_at,
            path="/",
            secure=cookie_secure,
            httponly=True,
            samesite="lax",
        )
        response.headers["Cache-Control"] = "no-store"
        return AccountResponse.from_account(issued.account)

    @router.post(
        "/auth/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=mutation_guard,
    )
    async def logout(
        response: Response,
        session_token: Annotated[str | None, Cookie(alias=cookie_name)] = None,
    ) -> None:
        if session_token:
            await auth.logout(session_token)
        response.delete_cookie(
            cookie_name,
            path="/",
            secure=cookie_secure,
            httponly=True,
            samesite="lax",
        )

    @router.get("/auth/me", response_model=AccountResponse)
    async def me(account: CurrentAccount) -> AccountResponse:
        return AccountResponse.from_account(account)

    @router.post(
        "/auth/password",
        response_model=AccountResponse,
        dependencies=mutation_guard,
    )
    async def change_password(
        body: ChangePasswordRequest,
        account: CurrentAccount,
    ) -> AccountResponse:
        try:
            updated = await auth.change_password(account, body.current_password, body.new_password)
        except InvalidCredentialsError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return AccountResponse.from_account(updated)

    @router.get("/admin/accounts", response_model=tuple[AccountResponse, ...])
    async def list_accounts(_admin: CurrentAdmin) -> tuple[AccountResponse, ...]:
        return tuple(AccountResponse.from_account(item) for item in await auth.list_accounts())

    @router.post(
        "/admin/accounts/{account_id}/reset-password",
        response_model=PasswordResetResponse,
        dependencies=mutation_guard,
    )
    async def reset_password(
        account_id: str, response: Response, _admin: CurrentAdmin
    ) -> PasswordResetResponse:
        account = await auth.repository.get_account(account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found")
        temporary = await auth.reset_password(account_id)
        response.headers["Cache-Control"] = "no-store"
        return PasswordResetResponse(
            account=AccountResponse.from_account(account),
            temporary_password=temporary,
        )

    # Bots

    @router.get("/bots", response_model=tuple[BotProfileResponse, ...])
    async def list_bots(account: CurrentAccount) -> tuple[BotProfileResponse, ...]:
        return tuple(BotProfileResponse.from_profile(item) for item in await bots.list(account.id))

    @router.post(
        "/bots",
        response_model=BotTokenResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=mutation_guard,
    )
    async def create_bot(
        body: BotProfileRequest,
        response: Response,
        account: CurrentAccount,
    ) -> BotTokenResponse:
        result = await _translate(bots.create(account.id, body.name, body.ip, body.port))
        response.headers["Cache-Control"] = "no-store"
        return BotTokenResponse(
            bot=BotProfileResponse.from_profile(result.profile),
            bearer_token=result.bearer_token,
        )

    @router.patch(
        "/bots/{bot_id}",
        response_model=BotProfileResponse,
        dependencies=mutation_guard,
    )
    async def update_bot(
        bot_id: str,
        body: BotProfileUpdateRequest,
        account: CurrentAccount,
    ) -> BotProfileResponse:
        profile = await _translate(
            bots.update(account.id, bot_id, name=body.name, ip=body.ip, port=body.port)
        )
        return BotProfileResponse.from_profile(profile)

    @router.post(
        "/bots/{bot_id}/rotate-token",
        response_model=BotTokenResponse,
        dependencies=mutation_guard,
    )
    async def rotate_bot_token(
        bot_id: str,
        response: Response,
        account: CurrentAccount,
    ) -> BotTokenResponse:
        result = await _translate(bots.rotate_token(account.id, bot_id))
        response.headers["Cache-Control"] = "no-store"
        return BotTokenResponse(
            bot=BotProfileResponse.from_profile(result.profile),
            bearer_token=result.bearer_token,
        )

    @router.post(
        "/bots/{bot_id}/verify",
        response_model=BotProfileResponse,
        dependencies=mutation_guard,
    )
    async def verify_bot(bot_id: str, account: CurrentAccount) -> BotProfileResponse:
        profile = await _translate(bots.verify(account.id, bot_id))
        return BotProfileResponse.from_profile(profile)

    @router.delete(
        "/bots/{bot_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=mutation_guard,
    )
    async def delete_bot(bot_id: str, account: CurrentAccount) -> None:
        await _translate(bots.delete(account.id, bot_id))

    @router.get("/bots/{bot_id}/diagnostics", response_model=BotDiagnosticsResponse)
    async def bot_diagnostics(bot_id: str, account: CurrentAccount) -> BotDiagnosticsResponse:
        profile = await _translate(bots.get(account.id, bot_id))
        stats = runtime.bot_stats(profile.id)
        return BotDiagnosticsResponse(
            bot=BotProfileResponse.from_profile(profile),
            decisions=stats.decisions,
            failures=dict(stats.failures),
            consecutive_failures=stats.consecutive_failures,
            recent=tuple(stats.recent),
        )

    # Matches for players

    @router.get("/matches/code/{code}", response_model=MatchPreviewResponse)
    async def preview_match(code: str, account: CurrentAccount) -> MatchPreviewResponse:
        return await code_attempt(account, matches.preview(code))

    @router.post(
        "/matches/join",
        response_model=MatchViewResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=mutation_guard,
    )
    async def join_match(body: JoinMatchRequest, account: CurrentAccount) -> MatchViewResponse:
        return await code_attempt(
            account,
            matches.join(account, body.code, body.kind, body.display_name, body.bot_profile_id),
        )

    @router.get("/me/matches", response_model=tuple[MyMatchResponse, ...])
    async def my_matches(account: CurrentAccount) -> tuple[MyMatchResponse, ...]:
        return await matches.my_matches(account)

    @router.get("/matches/{match_id}", response_model=MatchViewResponse)
    async def match_view(match_id: str, account: CurrentAccount) -> MatchViewResponse:
        return await _translate(matches.view(account, match_id))

    @router.delete(
        "/matches/{match_id}/entries/{entry_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=mutation_guard,
    )
    async def leave_match(match_id: str, entry_id: str, account: CurrentAccount) -> None:
        await _translate(matches.leave(account, match_id, entry_id))

    @router.get("/matches/{match_id}/table", response_model=PlayerTableStateResponse)
    async def player_table(match_id: str, account: CurrentAccount) -> PlayerTableStateResponse:
        return await _translate(runtime.player_state(account.id, match_id))

    @router.post(
        "/matches/{match_id}/table/action",
        response_model=PlayerTableStateResponse,
        dependencies=mutation_guard,
    )
    async def submit_player_action(
        match_id: str,
        body: PlayerActionRequest,
        account: CurrentAccount,
    ) -> PlayerTableStateResponse:
        return await _translate(runtime.submit_human_action(account.id, match_id, body))

    # Matches for admins

    @router.post(
        "/admin/matches",
        response_model=AdminMatchResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=mutation_guard,
    )
    async def create_match(body: MatchCreateRequest, admin: CurrentAdmin) -> AdminMatchResponse:
        return await _translate(matches.create(admin, body.name, body.config))

    @router.get("/admin/matches", response_model=tuple[AdminMatchSummaryResponse, ...])
    async def list_matches(_admin: CurrentAdmin) -> tuple[AdminMatchSummaryResponse, ...]:
        return await matches.admin_list()

    @router.get("/admin/matches/{match_id}", response_model=AdminMatchResponse)
    async def admin_match(match_id: str, _admin: CurrentAdmin) -> AdminMatchResponse:
        return await _translate(matches.admin_detail(match_id))

    @router.get("/admin/matches/{match_id}/table", response_model=PlayerTableStateResponse)
    async def spectate_match(match_id: str, _admin: CurrentAdmin) -> PlayerTableStateResponse:
        return await _translate(runtime.spectator_state(match_id))

    @router.post(
        "/admin/matches/{match_id}/start",
        response_model=AdminMatchResponse,
        dependencies=mutation_guard,
    )
    async def start_match(
        match_id: str,
        admin: CurrentAdmin,
        force: Annotated[bool, Query()] = False,
    ) -> AdminMatchResponse:
        return await _translate(matches.start(admin, match_id, force=force))

    def admin_command(
        path: str,
        method: Callable[[Account, str], Awaitable[AdminMatchResponse]],
        http_method: str = "POST",
    ) -> None:
        async def command(match_id: str, admin: CurrentAdmin) -> AdminMatchResponse:
            return await _translate(method(admin, match_id))

        router.add_api_route(
            path,
            command,
            methods=[http_method],
            response_model=AdminMatchResponse,
            dependencies=mutation_guard,
            name=f"admin_{method.__name__}",
        )

    admin_command("/admin/matches/{match_id}/pause", matches.pause)
    admin_command("/admin/matches/{match_id}/resume", matches.resume)
    admin_command("/admin/matches/{match_id}/end", matches.end)
    admin_command("/admin/matches/{match_id}/cancel", matches.cancel)
    admin_command("/admin/matches/{match_id}/code", matches.regenerate_code)
    admin_command("/admin/matches/{match_id}/code", matches.revoke_code, "DELETE")

    @router.delete(
        "/admin/matches/{match_id}/entries/{entry_id}",
        response_model=AdminMatchResponse,
        dependencies=mutation_guard,
    )
    async def kick_entry(
        match_id: str,
        entry_id: str,
        admin: CurrentAdmin,
    ) -> AdminMatchResponse:
        return await _translate(matches.kick(admin, match_id, entry_id))

    return router
