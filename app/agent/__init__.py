__all__ = ["AgentRouter", "search_hr_policy", "get_my_leave_balance", "get_my_attendance", "prepare_leave_request"]


def __getattr__(name):
    if name == "AgentRouter":
        from app.agent.router import AgentRouter

        return AgentRouter
    if name in {"search_hr_policy", "get_my_leave_balance", "get_my_attendance", "prepare_leave_request"}:
        from app.agent import tools

        return getattr(tools, name)
    raise AttributeError(name)
