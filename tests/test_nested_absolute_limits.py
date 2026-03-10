"""Test Decision #5: Absolute Limits Only (No Percentages)

Child budgets only support max_usd (absolute dollar amounts), not percentages.
This is a deliberate simplicity choice - optimizes for code readability and
predictability. Users can calculate percentages themselves if needed.
"""

import pytest

from shekel import budget


def test_only_dollar_amounts_supported():
    """Budget only accepts dollar amounts via max_usd parameter."""
    # These work - dollar amounts
    with budget(max_usd=10.00) as b1:
        assert b1.max_usd == 10.00

    with budget(max_usd=0.50) as b2:
        assert b2.max_usd == 0.50

    with budget(max_usd=None) as b3:
        # Track-only mode
        assert b3.max_usd is None


def test_no_percent_parameter_in_api():
    """Budget class does not have a 'percent' parameter."""
    # This should raise TypeError - 'percent' is not a valid parameter
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        budget(max_usd=10.00, percent=0.5)


def test_users_can_calculate_percentages_manually():
    """Users can calculate percentage-based budgets if needed."""
    with budget(max_usd=10.00, name="parent") as parent:
        # User wants 50% of parent for child
        child_limit = parent.max_usd * 0.5 if parent.max_usd else None

        with budget(max_usd=child_limit, name="child") as child:
            assert child.max_usd == 5.00


def test_absolute_limits_are_self_documenting():
    """Absolute limits are clear from reading the code."""
    # This code is immediately understandable
    with budget(max_usd=10.00, name="workflow"):
        with budget(max_usd=2.00, name="research"):
            pass  # Research stage gets $2
        with budget(max_usd=5.00, name="analysis"):
            pass  # Analysis stage gets $5

    # No need to look up what parent limit is or calculate percentages
    # The dollar amounts are right there in the code
