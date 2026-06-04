# Requires: pip install shekel[autogen] openai
"""
AutoGen demo: per-agent circuit breaking with shekel.

Shekel patches ConversableAgent.generate_reply transparently — every agent
turn gets a pre-execution budget gate with no agent or conversation changes.

Shows three patterns:
1. Global cap only — zero config, shekel auto-detects AutoGen
2. Per-agent caps — b.agent("name", max_usd=X)
3. b.tree() — full spend breakdown after the conversation
"""

import os


def main() -> None:
    try:
        from autogen import AssistantAgent, UserProxyAgent  # type: ignore[import]
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run: pip install shekel[autogen]")
        return

    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this demo.")
        return

    from shekel import budget
    from shekel.exceptions import AgentBudgetExceededError, BudgetExceededError

    llm_config = {
        "config_list": [{"model": "gpt-4o-mini", "api_key": os.environ["OPENAI_API_KEY"]}],
    }

    assistant = AssistantAgent(
        "assistant",
        llm_config=llm_config,
        system_message="You are a helpful assistant. Keep replies brief.",
    )
    critic = AssistantAgent(
        "critic",
        llm_config=llm_config,
        system_message="You are a critic. Give one-sentence feedback.",
    )
    user_proxy = UserProxyAgent(
        "user_proxy",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=1,
        code_execution_config=False,
    )

    # ------------------------------------------------------------------
    # 1. Global cap only — zero config, shekel auto-detects AutoGen
    # ------------------------------------------------------------------
    print("=== Global cap only ===")
    try:
        with budget(max_usd=1.00, name="global") as b:
            user_proxy.initiate_chat(
                assistant,
                message="Explain gradient descent in one sentence.",
                max_turns=2,
            )
        print(f"Done. Spent: ${b.spent:.4f}")
    except BudgetExceededError as e:
        print(f"Budget exceeded: {e}")

    # ------------------------------------------------------------------
    # 2. Per-agent caps — b.agent() keyed on agent.name
    # ------------------------------------------------------------------
    print("\n=== Per-agent caps ===")
    try:
        with budget(max_usd=2.00, name="agents") as b:
            b.agent("assistant", max_usd=0.80)
            b.agent("critic", max_usd=0.50)

            user_proxy.initiate_chat(
                assistant,
                message="What is a neural network?",
                max_turns=1,
            )
            # Second conversation — critic is now involved
            user_proxy.initiate_chat(
                critic,
                message="Is this explanation accurate: 'A neural network mimics the brain'?",
                max_turns=1,
            )

        print(f"Done. Spent: ${b.spent:.4f}")
        print(b.tree())
        # agents: $X.XX / $2.00
        #   [agent] assistant: $X.XX / $0.80  (X%)
        #   [agent] critic:    $X.XX / $0.50  (X%)

    except AgentBudgetExceededError as e:
        print(f"Agent '{e.agent_name}' hit its cap: ${e.spent:.4f} / ${e.limit:.2f}")
    except BudgetExceededError as e:
        print(f"Global budget exceeded: ${e.spent:.4f}")

    # ------------------------------------------------------------------
    # 3. b.tree() — spend breakdown after the fact
    # ------------------------------------------------------------------
    print("\n=== Final spend breakdown ===")
    print(b.summary())


if __name__ == "__main__":
    main()
