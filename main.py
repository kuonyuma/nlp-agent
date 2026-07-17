"""CLI adapter for the lifecycle-owning Backend Gateway Core."""

from __future__ import annotations

import asyncio
import sys

from core.identity import AuthenticatedPrincipal
from gateway.contracts import GatewayEventType, SubmitTurnRequest
from gateway.core import BackendGateway


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def check_config() -> bool:
    from configs.settings import settings

    config = settings.planner_llm
    print(f"Coordinator: {config['model_id']} ({config['base_url']})")
    print(f"Worker:      {settings.tool_llm['model_id']}")
    if not config.get("api_key_configured"):
        print("Missing DEEPSEEK_API_KEY; create .env in the project root.")
        return False
    return True


async def _input(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def main() -> None:
    if not check_config():
        raise SystemExit(1)

    principal = AuthenticatedPrincipal(
        user_id="local", workspace_ids=frozenset({"default"}), roles=frozenset({"admin"})
    )
    gateway = BackendGateway()
    await gateway.start()
    from server.agent.session_storage import get_active_session_id

    active_session_id = get_active_session_id()
    if active_session_id:
        try:
            await gateway.sessions.resolve(principal, active_session_id)
        except (FileNotFoundError, PermissionError):
            active_session_id = None
    if not active_session_id:
        active_session_id = (
            await gateway.create_session(principal, workspace_id="default", channel="cli")
        ).session_id

    print("Enter a question. Commands: /new, /sessions, /load <id>, /exit")
    try:
        while True:
            query = (await _input("\nYou: ")).strip()
            if not query:
                continue
            if query == "/exit":
                break
            if query == "/new":
                active_session_id = (
                    await gateway.create_session(
                        principal, workspace_id="default", channel="cli"
                    )
                ).session_id
                print(f"[system] New session: {active_session_id}")
                continue
            if query == "/sessions":
                for session in await gateway.sessions.list(principal):
                    print(f"- {session['session_id']} | {session.get('last_active', 0)}")
                continue
            if query.startswith("/load "):
                target = query.split(maxsplit=1)[1]
                try:
                    await gateway.sessions.resolve(principal, target)
                except (FileNotFoundError, PermissionError):
                    print("[system] Session not found")
                else:
                    active_session_id = target
                    print(f"[system] Loaded: {target}")
                continue

            accepted = await gateway.submit_turn(
                principal,
                SubmitTurnRequest(session_id=active_session_id, content=query),
            )
            printed = False
            async for event in gateway.stream_events(principal, accepted.turn_id):
                if event.type != GatewayEventType.MESSAGE_DELTA:
                    continue
                if event.payload.get("channel") == "reasoning":
                    continue
                delta = event.payload.get("delta", "")
                if not delta:
                    continue
                if not printed:
                    print("\nAgent: ", end="", flush=True)
                    printed = True
                print(delta, end="", flush=True)
            if printed:
                print()
            else:
                turn = await gateway.get_turn(principal, accepted.turn_id)
                print(f"\nAgent: {turn.final_text or turn.error_message or ''}")
    finally:
        await gateway.close()


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "chat"
    if command in {"serve", "web"}:
        from server.web.__main__ import run

        run()
    elif command in {"chat", "--chat", "-c"}:
        asyncio.run(main())
    else:
        print("Usage: python main.py [chat|serve]")
        raise SystemExit(2)
