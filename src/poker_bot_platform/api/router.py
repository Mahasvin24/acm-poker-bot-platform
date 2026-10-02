from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from poker_bot_platform.api.models import (
    AccountResponse,
    AdminCommandResponse,
    AdminTournamentRequest,
    AdminTournamentUpdateRequest,
    BotEndpointRegistrationResponse,
    BotEndpointRequest,
    EntrantRequest,
    EntrantResponse,
    LoginRequest,
    PlayerActionRequest,
    PlayerTableStateResponse,
    RegisterRequest,
)
from poker_bot_platform.api.security import SameOriginGuard
from poker_bot_platform.auth.models import Account, Entrant
from poker_bot_platform.auth.repository import AuthConflictError, AuthNotFoundError
from poker_bot_platform.auth.service import (
    AuthService,
    BotRegistrationResult,
    BotVerificationError,
    InvalidCredentialsError,
    InvalidSessionError,
)
from poker_bot_platform.domain import EntryKind, Role, TournamentConfig


class EntrantControlService(Protocol):
    async def register(
        self,
        account_id: str,
        tournament_id: str,
        kind: EntryKind,
        display_name: str,
    ) -> Entrant: ...

    async def configure_bot(
        self,
        account_id: str,
        tournament_id: str,
        ip: str,
        port: int,
    ) -> BotRegistrationResult: ...

    async def verify_bot(self, account_id: str, tournament_id: str) -> Entrant: ...


class AdminControlService(Protocol):
    async def create_tournament(
        self, tournament_id: str, config: TournamentConfig, actor_id: str
    ) -> AdminCommandResponse: ...
    async def update_draft(
        self, tournament_id: str, config: TournamentConfig, actor_id: str
    ) -> AdminCommandResponse: ...
    async def open_registration(
        self, tournament_id: str, actor_id: str
    ) -> AdminCommandResponse: ...
    async def seat(self, tournament_id: str, actor_id: str) -> AdminCommandResponse: ...
    async def start(self, tournament_id: str, actor_id: str) -> AdminCommandResponse: ...
    async def pause(self, tournament_id: str, actor_id: str) -> AdminCommandResponse: ...
    async def resume(self, tournament_id: str, actor_id: str) -> AdminCommandResponse: ...
    async def advance_level(self, tournament_id: str, actor_id: str) -> AdminCommandResponse: ...


class GameplayControlService(Protocol):
    async def player_state(
        self,
        account_id: str,
        tournament_id: str,
    ) -> PlayerTableStateResponse: ...

    async def submit_human_action(
        self,
        account_id: str,
        tournament_id: str,
        request: PlayerActionRequest,
    ) -> PlayerTableStateResponse: ...


def create_api_router(
    *,
    auth: AuthService,
    entrants: EntrantControlService,
    admin: AdminControlService,
    gameplay: GameplayControlService | None = None,
    allowed_origin: str,
    cookie_name: str = "poker_session",
    cookie_secure: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    same_origin = SameOriginGuard(allowed_origin)

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

    mutation_guard = [Depends(same_origin)]

    @router.post(
        "/auth/register",
        response_model=AccountResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=mutation_guard,
    )
    async def register(body: RegisterRequest) -> AccountResponse:
        try:
            account = await auth.register(body.email, body.password)
        except (ValueError, AuthConflictError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return AccountResponse.from_account(account)

    @router.post("/auth/login", response_model=AccountResponse, dependencies=mutation_guard)
    async def login(body: LoginRequest, response: Response) -> AccountResponse:
        try:
            issued = await auth.login(body.email, body.password)
        except (ValueError, InvalidCredentialsError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid email or password",
            ) from exc
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
    async def me(account: Annotated[Account, Depends(current_account)]) -> AccountResponse:
        return AccountResponse.from_account(account)

    @router.post(
        "/tournaments/{tournament_id}/entrant",
        response_model=EntrantResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=mutation_guard,
    )
    async def register_entrant(
        tournament_id: str,
        body: EntrantRequest,
        account: Annotated[Account, Depends(current_account)],
    ) -> EntrantResponse:
        try:
            entrant = await entrants.register(
                account.id,
                tournament_id,
                body.kind,
                body.display_name,
            )
        except (ValueError, AuthConflictError, AuthNotFoundError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return EntrantResponse.from_entrant(entrant)

    @router.put(
        "/tournaments/{tournament_id}/entrant/bot-endpoint",
        response_model=BotEndpointRegistrationResponse,
        dependencies=mutation_guard,
    )
    async def configure_bot(
        tournament_id: str,
        body: BotEndpointRequest,
        response: Response,
        account: Annotated[Account, Depends(current_account)],
    ) -> BotEndpointRegistrationResponse:
        try:
            result = await entrants.configure_bot(account.id, tournament_id, body.ip, body.port)
        except (ValueError, AuthConflictError, AuthNotFoundError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        response.headers["Cache-Control"] = "no-store"
        return BotEndpointRegistrationResponse(
            entrant=EntrantResponse.from_entrant(result.entrant),
            bearer_token=result.bearer_token,
        )

    @router.post(
        "/tournaments/{tournament_id}/entrant/bot-endpoint/verify",
        response_model=EntrantResponse,
        dependencies=mutation_guard,
    )
    async def verify_bot(
        tournament_id: str,
        account: Annotated[Account, Depends(current_account)],
    ) -> EntrantResponse:
        try:
            entrant = await entrants.verify_bot(account.id, tournament_id)
        except (
            ValueError,
            AuthConflictError,
            AuthNotFoundError,
            BotVerificationError,
        ) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return EntrantResponse.from_entrant(entrant)

    @router.post(
        "/admin/tournaments",
        response_model=AdminCommandResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=mutation_guard,
    )
    async def create_tournament(
        body: AdminTournamentRequest,
        account: Annotated[Account, Depends(current_admin)],
    ) -> AdminCommandResponse:
        return await admin.create_tournament(body.tournament_id, body.config, account.id)

    @router.put(
        "/admin/tournaments/{tournament_id}",
        response_model=AdminCommandResponse,
        dependencies=mutation_guard,
    )
    async def update_tournament(
        tournament_id: str,
        body: AdminTournamentUpdateRequest,
        account: Annotated[Account, Depends(current_admin)],
    ) -> AdminCommandResponse:
        return await admin.update_draft(tournament_id, body.config, account.id)

    def admin_command(path: str, method_name: str) -> None:
        async def command(
            tournament_id: str,
            account: Annotated[Account, Depends(current_admin)],
        ) -> AdminCommandResponse:
            method = cast(
                Callable[[str, str], Awaitable[AdminCommandResponse]],
                getattr(admin, method_name),
            )
            return await method(tournament_id, account.id)

        router.add_api_route(
            path,
            command,
            methods=["POST"],
            response_model=AdminCommandResponse,
            dependencies=mutation_guard,
            name=f"admin_{method_name}",
        )

    admin_command("/admin/tournaments/{tournament_id}/open", "open_registration")
    admin_command("/admin/tournaments/{tournament_id}/seat", "seat")
    admin_command("/admin/tournaments/{tournament_id}/start", "start")
    admin_command("/admin/tournaments/{tournament_id}/pause", "pause")
    admin_command("/admin/tournaments/{tournament_id}/resume", "resume")
    admin_command("/admin/tournaments/{tournament_id}/advance", "advance_level")

    if gameplay is not None:
        # Kept local to avoid coupling the API protocol definitions back to the
        # concrete runtime implementation.
        from poker_bot_platform.integration.runtime import (
            GameplayAccessError,
            GameplayConflictError,
            GameplayNotFoundError,
        )

        @router.get(
            "/tournaments/{tournament_id}/table",
            response_model=PlayerTableStateResponse,
        )
        async def player_table(
            tournament_id: str,
            account: Annotated[Account, Depends(current_account)],
        ) -> PlayerTableStateResponse:
            try:
                return await gameplay.player_state(account.id, tournament_id)
            except GameplayAccessError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(exc),
                ) from exc
            except GameplayNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=str(exc),
                ) from exc
            except GameplayConflictError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from exc

        @router.post(
            "/tournaments/{tournament_id}/table/action",
            response_model=PlayerTableStateResponse,
            dependencies=mutation_guard,
        )
        async def submit_player_action(
            tournament_id: str,
            body: PlayerActionRequest,
            account: Annotated[Account, Depends(current_account)],
        ) -> PlayerTableStateResponse:
            try:
                return await gameplay.submit_human_action(
                    account.id,
                    tournament_id,
                    body,
                )
            except GameplayAccessError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(exc),
                ) from exc
            except GameplayNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=str(exc),
                ) from exc
            except GameplayConflictError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from exc

    return router
