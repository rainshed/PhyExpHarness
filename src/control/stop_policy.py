"""Activity-bound completion policies; historical activities keep their contract."""

REVIEW_POLICY = 'stop-review-v1'
GOAL_POLICY = 'goal-or-budget-v1'
META_POLICY = 'meta-closeout-v1'
CONTROLLED_POLICIES = (REVIEW_POLICY, GOAL_POLICY, META_POLICY)
