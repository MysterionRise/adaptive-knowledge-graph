"""
The learner simulator (#307): a synthetic world for checking policies before there are learners.

Simulated learners with a hidden, continuous skill per concept practise under a policy for a
fixed time budget. The policy sees the production mastery estimate and a prerequisite DAG
that may be wrong; the world learns by the true one. The outcome is read from the hidden
state. See ``docs/adaptivity/README.md``, "The simulator".

| Module        | What it holds                                                              |
| ------------- | -------------------------------------------------------------------------- |
| ``worlds``    | Graphs, the world's assumptions, learners and the seeded random streams    |
| ``dags``      | The DAG a policy is given: the true one and its degraded variants          |
| ``policies``  | ``random``, ``textbook``, ``band-v1``, ``ready-first``, ``oracle``         |
| ``protocol``  | ``SimulationProtocol`` and the smoke test's ``SMOKE_PROTOCOL``             |
| ``runner``    | One learner under one policy, and the matrix of worlds and DAGs            |
| ``metrics``   | The primary metric, paired effects, AUC, the decision rule, JSON rendering |

A result of the simulator supports no claim about learners. It can show that the code does
what it says and how a ranking of policies holds up across assumed worlds.

The package imports the policy interface, the attempt schema, the production mastery update
and ``eval_stats``. It imports no web framework, no database client and no model. The
mastery update works on the learner models, and ``backend.app.student.models`` imports the
settings object: the environment and ``.env`` are read at import, and an environment the
application refuses stops the import. No setting is used in a run.
"""

from backend.app.student.simulation.dags import (
    STANDARD_DAGS,
    DagSpec,
    given_dag,
    precision_recall,
    true_dag,
)
from backend.app.student.simulation.metrics import (
    auc,
    decision,
    mc_standard_error,
    mean,
    paired_effect,
    primary_metric,
    render_json,
    standard_deviation,
    time_to_criterion,
)
from backend.app.student.simulation.policies import (
    BAD_POLICY,
    POLICY_NAMES,
    PolicySpec,
    RandomOrder,
    ReadyFirst,
    StuckOnLast,
    TextbookOrder,
    build_policy,
)
from backend.app.student.simulation.protocol import SMOKE_PROTOCOL, SimulationProtocol
from backend.app.student.simulation.runner import (
    LearnerOutcome,
    run_learner,
    run_matrix,
    run_policy,
)
from backend.app.student.simulation.worlds import (
    FIXTURE_GRAPH,
    ConceptGraph,
    Learner,
    LearnerTraits,
    World,
    WorldSpec,
    stream,
    synthetic_graph,
)

__all__ = [
    # Worlds
    "ConceptGraph",
    "FIXTURE_GRAPH",
    "Learner",
    "LearnerTraits",
    "World",
    "WorldSpec",
    "stream",
    "synthetic_graph",
    # Given DAGs
    "DagSpec",
    "STANDARD_DAGS",
    "given_dag",
    "precision_recall",
    "true_dag",
    # Policies
    "BAD_POLICY",
    "POLICY_NAMES",
    "PolicySpec",
    "RandomOrder",
    "ReadyFirst",
    "StuckOnLast",
    "TextbookOrder",
    "build_policy",
    # Protocol
    "SMOKE_PROTOCOL",
    "SimulationProtocol",
    # Runner
    "LearnerOutcome",
    "run_learner",
    "run_matrix",
    "run_policy",
    # Metrics
    "auc",
    "decision",
    "mc_standard_error",
    "mean",
    "paired_effect",
    "primary_metric",
    "render_json",
    "standard_deviation",
    "time_to_criterion",
]
