"""FastAPI routers included by the desktop application."""

from . import chat, command, file, knowledge, log, model, theme, tutorial, window

routers = (
    chat.router,
    command.router,
    file.router,
    knowledge.router,
    log.router,
    model.router,
    theme.router,
    tutorial.router,
    window.router,
)
