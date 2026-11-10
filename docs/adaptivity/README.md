# Adaptivity: what "adaptive" means here

This note pins down what the project may call adaptive. It covers what happens
in the code today and which activities the research says make a difference. It
also lays out the learner track that tests those activities, first in a
simulator and later with learners. The track is tracked in [#313](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/313). It
runs alongside the domain-method milestones in [ROADMAP.md](../../ROADMAP.md)
and does not change their definitions of done.

Sources checked on 9 November 2026 against abstracts, publisher records and
search snippets (full texts were not reachable); numbers that rest on secondary
summaries say so. File references are to `main` at commit `52f2dbf`.

## Summary

- **No behaviour is adaptive yet.** One rule asks the LLM, in the prompt, for
  an easy, medium or hard quiz. Nothing checks what comes back. The learner
  model behind that rule has never been fitted, and anyone with the API key can
  write to it.
- **The two labels.** "Adaptive" means a learner-state decision that passes
  two tests: it changes only when learner state changes, and the state is
  valid. "Beneficial" means it also beats a non-adaptive baseline on an
  outcome fixed in advance, and it always names the evidence level, either
  "in simulation" or "in a pilot".
- **Where adaptation helps.** The research points at grounded corrective
  feedback, spaced retrieval practice and mastery correctives more than at
  clever sequencing. Whether the knowledge graph helps in choosing *what next*
  is an open hypothesis, and the closest prior evidence (ALEKS) found no
  advantage over traditional teaching.
- **The order of work.** First a simulator that can falsify our own designs,
  then server-side evidence (graded attempts, a held-out item pool), then
  feedback. A mastery loop over the curated prerequisite graph comes last, and
  only if the simulator's decision rule supports it.
- **No learners for now.** Until there are learners (and per-learner identity,
  [#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)),
  no learning gain is claimed.

## Two labels and three tests

| Test | Passes when | Checked by |
| --- | --- | --- |
| 1. Decision | The decision is a declared function of learner state plus declared context (time, content, seed). It does not change when an undeclared input changes, and it changes for state differences named in advance. A **manipulation check** shows that the delivered items differ the way the decision record says, judged without trusting the LLM's own difficulty label. | Counterfactual tests (the pattern of [#210](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/210)) and a delivered-item check |
| 2. Validity | The state comes from server-graded attempts. Its predicted probability of a correct answer meets AUC, expected calibration error and Brier thresholds fixed in advance, and it beats a running-accuracy baseline. | In simulation: against the latent true state. With learners: against held-out next attempts. |
| 3. Value | The policy beats a non-adaptive baseline on an outcome that does not depend on the policy, fixed in advance. | The simulation protocol or a pilot protocol |

- **"Adaptive"** requires tests 1 and 2.
- **"Beneficial"** requires test 3 and always carries its evidence level:
  "beneficial in simulation under assumptions A1 to An" or "beneficial in a
  pilot under protocol vX".
- **Wording until something passes.** The band rule is described as
  "difficulty requested by prompt; neither the delivered difficulty nor the
  mastery estimate is validated".
- **Never say these** without the evidence above: "personalised", "adapts to
  each learner", "calibrated difficulty", "mastery accuracy", "learning gains"
  and "IRT".

## What happens today

| Decision | Where | What it does |
| --- | --- | --- |
| Quiz difficulty band | `backend/app/student/models.py:54`, `backend/app/api/routes/quiz.py:163` | Mastery below 0.4 asks for easy questions, up to 0.7 medium, above that hard. The band is a prompt instruction only: the LLM labels its own difficulty, off-band questions are returned unchanged, and `adapted=True` is hard-coded (`quiz.py:181`). All questions in a quiz use one band, and each quiz is generated from a single retrieved chunk (`quiz_generator.py:76`). |
| Mastery estimate | `backend/app/student/student_service.py:236-297` | Four-parameter BKT with constants that were never fitted: transit 0.1, slip 0.1, guess 0.25, prior 0.3 (`models.py:27-29`, `core/settings.py:249`). From the prior, one correct answer gives 0.65 and two give about 0.88, so two answers jump from easy to hard. There is no forgetting (`last_assessed` is written, never read) and no attempt history, only counters. |
| What mastery is keyed by | `frontend/components/Quiz.tsx:348`, `backend/app/student/quiz_generator.py:158` | The free-text quiz topic, with no subject. Only 7 of the 23 offered topics resolve to a graph concept ([#108](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/108)). `/student/mastery` accepts `subject` but drops it (`quiz.py:233-237`). |
| Grading | `backend/app/ui_payloads/quiz.py:15`, `Quiz.tsx:331` | In the browser. The answer key and explanation are sent with the questions, and any caller with the API key can post any mastery update ([#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)). The interface uses a single `"default"` learner ([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73)). |
| Recommendations | `backend/app/student/recommendation_service.py:55-61` | Remediation below a 50% quiz score, advancement above 80%. Mastery is displayed, not used. Prerequisites come from glossary-derived PREREQ edges, some of them wrong ([#223](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/223)). The "deep dive" is LLM text at temperature 0.7 with no retrieved source (`recommendation_service.py:263-272`). |
| Learning path | `backend/app/api/routes/learning_path.py:86` | The PREREQ ancestors of a concept, the same for every learner. It reads `chapter` from concepts (`:92`), but no concept has that property. |
| Tutor (`/ask`) | `backend/app/api/routes/ask.py` | Learner-agnostic, and it answers directly. |
| Measurement | `scripts/evaluate_rag.py` | Retrieval and answer quality only. Nothing measures quiz quality, decision quality or learning. |

**Overclaims to correct:**

- `demo-slides/index.html:432`: "Difficulty auto-targets student mastery
  level".
- `docs/demo/CLIENT_LEAVE_BEHIND.md:20`: "practice adapts to each learner's
  mastery".

## Assets in the sources, and a contamination problem

The OpenStax sources already hold material a learner track needs:

- **Learning objectives.** "By the end of this section, you will be able to"
  blocks: 132 in US History and 137 in Economics.
- **Author-written review questions with keys.** US History
  (`data/raw/us_history`) has 274 four-option multiple-choice items in 133
  sections, mostly two per section, plus 135 keyed free-response items.
  Economics has review, self-check and critical-thinking sections, but its raw
  files are not in the repository, so its keyed item count is unknown until
  ingest.
- **Book order.** Every ingest record carries its chapter and section, which
  gives a textbook-order baseline for free.

**The contamination problem.** Those questions **and their answer keys are
inside the retrieval chunks today**:

- `strip_structural_sections` (`backend/app/kg/markup.py`) runs only in the
  graph builder (`backend/app/kg/builder.py:668`).
- The RAG chunker cleans markup (`backend/app/rag/chunker.py:67`), and
  `scripts/index_to_opensearch.py:52` chunks whole records.
- The quiz generator's reference-section filter looks at section metadata
  only, so it does not catch them.

The quiz generator and `/ask` can therefore retrieve a review question with
its key. Until the one planned re-seed
([#215](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/215))
drops these sections from the chunks, they cannot serve as a held-out pool.

## What the evidence says

Each row names its comparator, because the same intervention looks very
different against "no instruction" and against "the same content without the
adaptive part".

| Lever | What was found | Strength for this repository |
| --- | --- | --- |
| Feedback granularity | Against no tutoring, human tutoring d 0.79 and intelligent tutoring systems d 0.76 (VanLehn 2011). The split by interaction (answer-based 0.31, step-based 0.76, substep 0.40) comes from VanLehn's own summaries. | Strong. Our quizzes are answer-based. Step-based tasks are the largest lever but also the costliest, so they are deferred. |
| Elaborated, corrective feedback | Elaborated feedback (what, how, why) is generally more effective than verification alone, with conflicting findings (Shute 2008). Feedback averages d 0.48, and feedback carrying more information works better (Wisniewski, Zierer & Hattie 2020). Feedback after multiple-choice items raises correct recall and reduces lure intrusions (Butler & Roediger 2008). | Strong and cheap. Each item already has an explanation and a source chunk. |
| Retrieval practice | Against restudy, g 0.50 over 159 effect sizes (Rowland 2014). Against all comparison conditions pooled, g 0.61 under fixed effects and 0.70 under random effects, with multiple-choice practice effective (Adesope, Trevisan & Sundararajan 2017). | Strong in general. Both arms of an adaptive-versus-fixed comparison quiz, so the expected difference between them is far smaller. |
| Spacing | Spaced against massed retrieval g 0.74. Expanding against uniform gaps g 0.034, not significant (Latimier, Peyre & Ramus 2021). Equal spacing won at two days mainly by delaying the first test (Karpicke & Roediger 2007, vocabulary pairs). The best gap grows with the retention interval, about 20 to 40% of a one-week delay (Cepeda et al. 2008). | Strong for fact-like material, thinner for conceptual material. A uniform-gap heuristic is enough; a fitted memory model is not needed. |
| Successive relearning | Retrieval to criterion across several spaced sessions raised course exam scores by more than 10% and held up 24 days later (Rawson, Dunlosky & Sciartelli 2013). | Moderate to strong. It defines mastery as spaced, repeated success instead of one streak. |
| Mastery learning | Positive exam effects across 108 controlled evaluations (Kulik, Kulik & Bangert-Drowns 1990; the mean of about 0.5 SD appears in secondary summaries). Gains are modest on tests tied to the material and absent on broader standardised measures (Slavin 1987). Bloom's 2 SD tutoring and 1 SD mastery figures (Bloom 1984) are a historical reference, not a target. | Moderate. It costs time, so the simulator charges time. |
| Cognitive level | Fact-only retrieval quizzes did not improve higher-order test performance; mixed quizzes did best (Agarwal 2019). | Strong caveat: fact-recall multiple-choice items alone will not build understanding. |
| Selection by a knowledge-space frontier | ALEKS was "as good as, but not better than" traditional teaching (Fang et al. 2019). Against traditional instruction g 0.05, as a supplement g 0.43 (Sun et al. 2021). | Weak. This is the mechanism closest to "the graph picks what next". |
| Sequencing policies | Over half of the studies comparing reinforcement-learning sequencing policies with baselines found them significantly better, and they did best when constrained by learning-science theory (Doroudi, Aleven & Brunskill 2019). | Mixed. Strong baselines matter. |
| LLM help | During practice GPT-4 access raised performance by 48% (base) and 127% (tutor). Once access was removed, base users scored 17% lower on the exam, while the tutor's guardrails largely removed that harm, without an exam gain (Bastani et al. 2025). A designed AI tutor beat in-class active learning on immediate post-tests (Kestin et al. 2025, N 194, physics). ChatGPT hints gave gains equivalent to human-written hints but failed quality checks on 32% of problems before self-consistency (Pardos & Bhandari 2024). | Strong warning. Assisted performance is not learning, and generated help needs a correctness gate. |
| Difficulty from text | Predicting multiple-choice item difficulty from item text proved hard in the BEA 2024 shared task (Yaneva et al. 2024). | Negative for the LLM's self-labelled difficulty. Difficulty should come from responses once they exist, for example Elo (Pelánek 2016). |
| Evaluating policies offline | Offline evaluation overestimates new policies unless they are tested against several student models, including ones that differ from the policy's own (Doroudi, Aleven & Brunskill 2017). | Defines the simulator below. |
| Effect sizes to expect | The median effect across about 750 education RCTs with standardised outcomes is about 0.10 SD; the suggested benchmarks are under 0.05 small, 0.05 to 0.20 medium and 0.20 or more large (Kraft 2020; the cut-offs come from secondary summaries). | Any pilot here is small, so it is a feasibility study. |

## What the graph is for: a hypothesis

The knowledge graph is the project's domain model: concepts, prerequisites,
definitions and sources. It can serve the learner track in three ways:

- deciding what a learner is ready for (the ready-to-learn frontier);
- locating the root cause of a failure (a weak prerequisite);
- spreading the evidence from a short placement probe.

Whether any of this beats a well-run fixed order is **an open question**. The
simulator therefore separates two effects, fixed in advance:

- **Loop effect** = `mastery-textbook` minus `textbook`. This is the gain from
  correctives, feedback and spaced relearning in book order.
- **Graph effect** = `frontier-v1` on curated edges minus `mastery-textbook`.
  This is the extra gain from letting the graph choose. It may be zero.

**The adaptive slice.** Graph-driven decisions run only inside an adaptive
slice: the connected part of the curated prerequisite graph
([#223](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/223)),
versioned as a domain artifact
([#211](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/211)).
Outside it, a concept with no curated prerequisites would always look "ready",
and the frontier would say nothing.

## Target design

### Policy interface and decision records ([#306](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/306))

Learner-state decisions move into `backend/app/student/policy/`:

- **Policies.** Each policy has an id and a version. The band rule becomes
  `band-v1`, and `StudentProfile.get_target_difficulty` stays as a shim, so
  the #210 tests keep pinning it.
- **Decision records.** Every decision returns a record holding the policy id
  and version, the action, the learner state it used, and the graph edges it
  used with their provenance.
- **Uses of the record.** It is what the counterfactual tests and the
  manipulation check inspect, and what a "why this next?" explanation would
  show.
- **Off-policy evaluation is not claimed.** It needs stochastic policies with
  consented exploration, and these policies are deterministic.

### Attempt log and the assisted rule ([#308](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/308))

An append-only `attempts` table goes in the SQLite store that
[#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74)
adds for persisted quizzes.

- **One row per attempt:** opaque learner id, item id, concept ids, chosen
  option id, correctness, latency, the `assisted` flag, decision-record id,
  model versions, `source` (real or simulated) and timestamp.
- **Replayable mastery.** Mastery can be recomputed from the log, so the
  learner model can be refitted later. No free text is stored, and delete and
  export go through `reset_profile`.
- **What counts as assisted.** An attempt is assisted when a hint was served,
  source or re-teach text was shown in the same episode, it is a second try on
  the same item, or practice-mode `/ask` was used in the session. The server
  sets the flag from its own records, never the client.
- **Outcomes** count only first, unassisted attempts.
- **Estimation** counts help requested before the first response as incorrect
  (the ASSISTments convention). The simulator compares this with ignoring
  assisted attempts.

### A held-out measurement pool ([#309](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/309))

The textbook's own multiple-choice review items become a measurement pool,
**never served in practice**.

- **Excluded from retrieval.** The pool needs the structural sections dropped
  from the retrieval chunks first, in #215.
- **Mapping.** Items belong to a section, not a concept, so each item maps
  from section to concepts with recorded provenance. Section learning
  objectives are attached alongside.
- **Free-response items** are left out of measurement.
- **Reliability.** The pool's KR-20 reliability is reported.
- **Comparator.** It is the human-written comparator for the generated-quiz
  audit ([#230](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/230)).
- **Practice items** stay generated, from concept-tagged chunks
  ([#108](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/108)).

### Feedback ([#310](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/310))

Build on today's explanation and source chunk:

- **Rationales.** Each wrong option gets a rationale, stored at generation
  time.
- **Answer and citation.** The correct answer and its explanation are always
  shown after an item, with the source chunk rendered as a citation.
- **Correctness gate.** A self-consistency check runs before a generated item
  or hint is shown.
- **Checklist.** A behaviour checklist replaces the answer rubric for this
  purpose: hints withhold the key, and feedback cites its chunk and agrees
  with the key.
- **Baseline.** Today's single explanation.

### A mastery loop over the graph, later ([#312](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/312))

`frontier-v1` runs inside the adaptive slice and is built only if the
simulator's decision rule supports it.

- **Selection.** It picks the next concept from the ready-to-learn frontier.
- **Correctives.** After a failure it re-teaches from the source and then
  probes the weakest curated prerequisite.
- **Mastery.** A concept counts as mastered only after correct, unassisted
  retrieval in two to three spaced sessions (successive relearning, with a
  uniform-gap scheduler). An immediate retest only triggers more correctives.
- **What it replaces.** The score thresholds in `recommendation_service.py`,
  and `/learning-path` starts from the learner's frontier.

## The simulator

The simulator is how this project can be wrong cheaply. It is built as a
robust evaluation matrix: every policy is run against several worlds, most of
which do not share its assumptions. The core comes in [#307](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/307) and the
robustness extensions in [#311](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/311). Code goes in
`backend/app/student/simulation/` and `scripts/simulate_learners.py`, run by
`make simulate`.

| Axis | Values |
| --- | --- |
| World structure | A synthetic prerequisite DAG with prerequisite strength none, weak or strong. Learning is gated by prerequisites with some leak, and some learners hold knowledge that contradicts the DAG. Later worlds add IRT-style responses, forgetting and item memorisation. |
| The DAG the policy is given (crossed with the world) | The true DAG; precision 0.6 or 0.8; recall 0.6 or 0.8; 10 to 20% reversed edges; a chapter chain; no DAG; a degree-preserving shuffle |
| Item-to-concept mapping | Correct, or with a set error rate (robustness extension) |
| Policies | `random`, `textbook`, `band-v1` (textbook order plus band difficulty), `mastery-textbook`, `frontier-v1` and its DAG ablations, and an `oracle` that applies the policy's own rule to the true state |
| Effect of correctives, hints and feedback | Swept, including zero, to find the break-even point |

**Primary metric.** The mean, over a fixed and equally weighted set of slice
concepts, of the true probability of answering a fresh item correctly. It is
computed analytically from the latent state at a retention delay D. Every
policy gets the same time budget, and items, hints and reading all cost time,
so re-teaching is not free.

**Secondary metrics:**

- time to criterion;
- AUC, expected calibration error and Brier score of the policy's estimates
  against the truth;
- the optimism gap: performance under the policy's own model minus
  performance under the others;
- over- and under-practice per learner type;
- a mastery-threshold sweep;
- recovery of BKT parameters from simulated logs.

**Statistics:**

- Learners are paired across policies by seed (common random numbers).
- Results are effect sizes with Monte Carlo standard errors. There are no
  p-values, because the number of simulated learners is arbitrary.
- **Decision rule, frozen with the protocol** (`docs/evals/simulation-protocol.md`)
  before `frontier-v1` exists: a policy goes forward when it gains at least
  +δ in the primary cell and loses no more than δ in every other cell.

**What simulation can support:** that the code does what it says; how
rankings hold up across plausible worlds; how much wrong or missing
prerequisite edges cost, which turns #223's precision bar into a requirement
derived under stated assumptions; worst-case behaviour such as over-practice
or never reviewing; and which policies are not worth piloting.

**What it cannot support:** learning gains in people, effect sizes for a
pilot, real item difficulties or BKT parameter values. Simulated students do
not respond to natural-language hints, so feedback quality is judged by the
behaviour checklist and, later, by a pilot. LLM-role-played learners are not
used.

**The CI smoke test** runs a few learners on a small fixture graph in under 5
seconds. It checks that a fixed seed gives identical output, that the oracle
beats `random`, and that `random` beats a deliberately bad policy. It never
asserts that a new policy wins.

## A pilot, when there are learners

A pilot needs per-learner identity
([#73](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/73))
and consent, and is not scheduled. Its protocol is frozen before it runs.

- **Design.** Within each learner, concept clusters are randomised to
  `frontier-v1` or textbook order.
  - Clusters are prerequisite-closed, disjoint and drawn from different units,
    with no prerequisite edges across arms.
  - Each cluster gets the same time and item budget, in counterbalanced order,
    with the same delay from study to test.
- **Isolation.** Feedback and spacing are identical in both arms, so only
  selection and gating differ.
- **Outcome.** The primary outcome is a delayed post-test from the held-out
  pool, covering every randomised cluster whether or not the learner reached
  it (intention to treat). Unassisted checkpoints are secondary.
- **Analysis.** A mixed-effects model with learner random effects, attrition
  reported by arm, and a sensitivity analysis.
- **Size.** The minimum detectable effect comes from a power analysis anchored
  on Kraft (2020), not from the simulator. Unless it is about 0.2 SD or less,
  the pilot is a feasibility and fidelity study.
- **What it can show.** Outcome claims are limited to textbook multiple-choice
  recall. The pilot tests the loop within clusters, not long-range propagation
  through the graph.

## Privacy

- Attempts stay in the local SQLite store under an opaque learner id, with no
  free text.
- Simulated data goes to a separate file.
- Learner history never goes into a prompt for a remote LLM unless a setting
  allows it explicitly, consistent with `PRIVACY_LOCAL_ONLY`.

## Phases and issues

Learner-track items are Should items in their milestones. They may slip; the
domain milestones' tags do not wait for them.

| When | Item | Issue | Depends on |
| --- | --- | --- | --- |
| v0.5.0 | Counterfactual and BKT property tests, plausibility constraints, the two-label wording | [#210](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/210) (comment) | none |
| v0.5.0 | Drop the structural sections from the retrieval chunks in the one re-seed | [#215](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/215) (comment) | none |
| v0.6.0 W5 | Policy interface with decision records; `band-v1` | [#306](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/306) | #210 |
| v0.6.0 W5-W6 | Simulator core and frozen simulation protocol | [#307](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/307) | policy interface |
| v0.7.0 W8 | Server-side grading writes attempts; concept-id mastery keys | [#74](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/74), [#108](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/108) (comments) | none |
| v0.7.0 W8 | Attempt log with mastery replay and the assisted flag | [#308](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/308) | #74 |
| v0.7.0 W8-W9 | Held-out measurement pool from the textbook review items | [#309](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/309) | #215, #108 |
| v0.7.0 W9 | Per-distractor rationales, rendered citations, correctness gate | [#310](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/310) | #74 |
| v0.7.0 W9 | Simulator robustness worlds, calibration gate, break-even sweeps | [#311](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/311) | simulator core |
| Later | `frontier-v1` mastery loop | [#312](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/312) | #223, #108, simulator decision rule |
| Later | Placement probe, opt-in practice mode for `/ask`, pilot protocol | [#313](https://github.com/MysterionRise/adaptive-knowledge-graph/issues/313) (checklist) | `frontier-v1`, #73 |

## Deferred

- **Step-based tasks.** Economics graph and calculation problems, and history
  sourcing steps. The largest effect in the tutoring literature, and the most
  work.
- **Item and learner calibration.** Elo, IRT, PFA or AFM, and fitted BKT. They
  need real responses.
- **Fitted memory models (FSRS) and deep knowledge tracing.** Not justified at
  this scale.
- **LLM-simulated learners.**
- **Personalising `/ask` from learner history.**
- **Items that test several concepts at once.**

## Non-goals

- No claim that the LLM's difficulty labels are calibrated.
- No "adaptive" without tests 1 and 2, and no "beneficial" without its
  evidence level.
- No learning-gain claim without a pilot run under a frozen protocol.
- Assisted performance (with hints, sources or the tutor open) is never
  reported as learning.

## References

- Adesope, O. O., Trevisan, D. A., & Sundararajan, N. (2017). Rethinking the use of tests: A meta-analysis of practice testing. *Review of Educational Research, 87*(3), 659-701. <https://doi.org/10.3102/0034654316689306>
- Agarwal, P. K. (2019). Retrieval practice & Bloom's taxonomy: Do students need fact knowledge before higher order learning? *Journal of Educational Psychology, 111*(2), 189-209.
- Bastani, H., Bastani, O., Sungu, A., Ge, H., Kabakcı, Ö., & Mariman, R. (2025). Generative AI without guardrails can harm learning: Evidence from high school mathematics. *Proceedings of the National Academy of Sciences, 122*, e2422633122.
- Bloom, B. S. (1984). The 2 sigma problem: The search for methods of group instruction as effective as one-to-one tutoring. *Educational Researcher, 13*(6), 4-16. <https://doi.org/10.3102/0013189X013006004>
- Butler, A. C., & Roediger, H. L., III. (2008). Feedback enhances the positive effects and reduces the negative effects of multiple-choice testing. *Memory & Cognition, 36*(3), 604-616. <https://doi.org/10.3758/MC.36.3.604>
- Cepeda, N. J., Vul, E., Rohrer, D., Wixted, J. T., & Pashler, H. (2008). Spacing effects in learning: A temporal ridgeline of optimal retention. *Psychological Science, 19*(11), 1095-1102. <https://doi.org/10.1111/j.1467-9280.2008.02209.x>
- Doroudi, S., Aleven, V., & Brunskill, E. (2017). Robust evaluation matrix: Towards a more principled offline exploration of instructional policies. *Proceedings of the Fourth ACM Conference on Learning @ Scale*, 3-12. <https://doi.org/10.1145/3051457.3051463>
- Doroudi, S., Aleven, V., & Brunskill, E. (2019). Where's the reward? A review of reinforcement learning for instructional sequencing. *International Journal of Artificial Intelligence in Education, 29*(4), 568-620. <https://doi.org/10.1007/s40593-019-00187-x>
- Fang, Y., Ren, Z., Hu, X., & Graesser, A. C. (2019). A meta-analysis of the effectiveness of ALEKS on learning. *Educational Psychology, 39*(10), 1278-1292. <https://doi.org/10.1080/01443410.2018.1495829>
- Karpicke, J. D., & Roediger, H. L., III. (2007). Expanding retrieval practice promotes short-term retention, but equally spaced retrieval enhances long-term retention. *Journal of Experimental Psychology: Learning, Memory, and Cognition, 33*(4), 704-719.
- Kestin, G., Miller, K., Klales, A., Milbourne, T., & Ponti, G. (2025). AI tutoring outperforms in-class active learning: An RCT introducing a novel research-based design in an authentic educational setting. *Scientific Reports, 15*, 17458. <https://doi.org/10.1038/s41598-025-97652-6>
- Kraft, M. A. (2020). Interpreting effect sizes of education interventions. *Educational Researcher, 49*(4), 241-253. <https://doi.org/10.3102/0013189X20912798>
- Kulik, C.-L. C., Kulik, J. A., & Bangert-Drowns, R. L. (1990). Effectiveness of mastery learning programs: A meta-analysis. *Review of Educational Research, 60*(2), 265-299. <https://doi.org/10.3102/00346543060002265>
- Latimier, A., Peyre, H., & Ramus, F. (2021). A meta-analytic review of the benefit of spacing out retrieval practice episodes on retention. *Educational Psychology Review, 33*, 959-987. <https://doi.org/10.1007/s10648-020-09572-8>
- Pardos, Z. A., & Bhandari, S. (2024). ChatGPT-generated help produces learning gains equivalent to human tutor-authored help on mathematics skills. *PLOS ONE, 19*(5), e0304013. <https://doi.org/10.1371/journal.pone.0304013>
- Pelánek, R. (2016). Applications of the Elo rating system in adaptive educational systems. *Computers & Education, 98*, 169-179. <https://doi.org/10.1016/j.compedu.2016.03.017>
- Rawson, K. A., Dunlosky, J., & Sciartelli, S. M. (2013). The power of successive relearning: Improving performance on course exams and long-term retention. *Educational Psychology Review, 25*(4), 523-548. <https://doi.org/10.1007/s10648-013-9240-4>
- Rowland, C. A. (2014). The effect of testing versus restudy on retention: A meta-analytic review of the testing effect. *Psychological Bulletin, 140*(6), 1432-1463. <https://doi.org/10.1037/a0037559>
- Shute, V. J. (2008). Focus on formative feedback. *Review of Educational Research, 78*(1), 153-189. <https://doi.org/10.3102/0034654307313795>
- Slavin, R. E. (1987). Mastery learning reconsidered. *Review of Educational Research, 57*(2), 175-213.
- Sun, S., Else-Quest, N. M., Hodges, L. C., French, A. M., & Dowling, R. (2021). The effects of ALEKS on mathematics learning in K-12 and higher education: A meta-analysis. *Investigations in Mathematics Learning, 13*(3), 182-196. <https://doi.org/10.1080/19477503.2021.1926194>
- VanLehn, K. (2011). The relative effectiveness of human tutoring, intelligent tutoring systems, and other tutoring systems. *Educational Psychologist, 46*(4), 197-221.
- Wisniewski, B., Zierer, K., & Hattie, J. (2020). The power of feedback revisited: A meta-analysis of educational feedback research. *Frontiers in Psychology, 10*, 3087. <https://doi.org/10.3389/fpsyg.2019.03087>
- Yaneva, V., North, K., Baldwin, P., Ha, L. A., Rezayi, S., Zhou, Y., Choudhury, S. R., Harik, P., & Clauser, B. E. (2024). Findings from the first shared task on automated prediction of difficulty and response time for multiple-choice questions. *Proceedings of the 19th Workshop on Innovative Use of NLP for Building Educational Applications (BEA 2024)*, 470-482. <https://aclanthology.org/2024.bea-1.39>
