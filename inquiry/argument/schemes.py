"""
Argumentation schemes and their critical questions.

Each scheme is a defeasible inference pattern (Walton, Reed & Macagno 2008).
Its critical questions come in two kinds, following the burden-of-proof
treatment in Carneades (Gordon, Prakken & Walton 2007):

    assumption  the proponent must discharge it before the argument is
                applicable at all. An open assumption makes the argument
                inapplicable; it then neither supports nor attacks.
    exception   the argument stands unless the opponent raises it with
                grounds. Raising it is an undercutting attack.

`probes` says what the question is really testing — a premise, the
inference (warrant), or the conclusion — which tells the critic which
attack type a failed answer becomes. `sep` names the SEP entries whose
treatment the question distils; the stance taken is stated in `stance`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CQKind = Literal["assumption", "exception"]
Probe = Literal["premise", "inference", "conclusion"]


class CriticalQuestion(BaseModel):
    id: str
    text: str
    kind: CQKind
    probes: Probe
    sep: list[str] = Field(default_factory=list)


class Scheme(BaseModel):
    name: str
    title: str
    description: str
    premises: list[str] = Field(description="Premise slots, in plain words.")
    conclusion: str = Field(description="Shape of the conclusion.")
    default_strength: Literal["weak", "moderate", "strong"] = "moderate"
    critical_questions: list[CriticalQuestion]
    sep: list[str] = Field(default_factory=list)
    stance: str = Field(default="", description="Which position among SEP's surveyed views the scheme adopts, and why.")

    def cq(self, cq_id: str) -> CriticalQuestion:
        return next(q for q in self.critical_questions if q.id == cq_id)

    def assumptions(self) -> list[CriticalQuestion]:
        return [q for q in self.critical_questions if q.kind == "assumption"]

    def exceptions(self) -> list[CriticalQuestion]:
        return [q for q in self.critical_questions if q.kind == "exception"]


def _cq(id: str, text: str, kind: CQKind, probes: Probe, sep: list[str] | None = None) -> CriticalQuestion:
    return CriticalQuestion(id=id, text=text, kind=kind, probes=probes, sep=sep or [])


T = "Epistemological Problems of Testimony"
EV = "Evidence"
CONF = "Confirmation"
CM = "Causation and Manipulability"
CF = "Counterfactual Theories of Causation"
IL = "Inductive Logic"
PI = "The Problem of Induction"
AB = "Abduction"
AN = "Analogy and Analogical Reasoning"
MS = "Models in Science"
CS = "Computer Simulations in Science"
SO = "Scientific Objectivity"
DR = "Defeasible Reasoning"
AA = "Argument and Argumentation"


SCHEMES: dict[str, Scheme] = {}


def _register(s: Scheme) -> Scheme:
    SCHEMES[s.name] = s
    return s


# ---------------------------------------------------------------------------
# Source-based schemes
# ---------------------------------------------------------------------------

_register(Scheme(
    name="expert_opinion",
    title="Argument from expert opinion",
    description="A source with recognised expertise in the relevant field asserts the claim.",
    premises=["Source S is an expert in domain D", "Claim A falls within D", "S asserts A"],
    conclusion="A is plausibly true",
    critical_questions=[
        _cq("expertise", "Is S in fact an expert in D, by credentials or track record?", "assumption", "premise", [T]),
        _cq("field", "Does A fall within D, rather than an adjacent field?", "assumption", "premise", [T]),
        _cq("assertion", "Did S assert A, in these terms, rather than something weaker?", "assumption", "premise", [T]),
        _cq("basis", "Is S's assertion grounded in evidence S is in a position to have?", "assumption", "inference", [T, EV]),
        _cq("consensus", "Do other experts in D disagree with A?", "exception", "conclusion", [T, "Disagreement"]),
        _cq("bias", "Does S have an interest that would shape this assertion?", "exception", "inference", [T, SO]),
    ],
    sep=[T, AA],
    stance="Testimony is taken as a defeasible source of justification (anti-reductionist default) but the "
           "harness still requires positive grounds for expertise and basis, which is the reductionist's demand. "
           "The two are reconciled by making those grounds assumptions the proponent must supply.",
))

_register(Scheme(
    name="position_to_know",
    title="Argument from position to know",
    description="A source that was in a position to observe or know the facts reports them.",
    premises=["Source S was in a position to know whether A", "S reports A"],
    conclusion="A is plausibly true",
    critical_questions=[
        _cq("access", "Was S actually in a position to know: present, with access, with competence to observe?", "assumption", "premise", [T]),
        _cq("report", "Does S's report state A, or has it been paraphrased into A?", "assumption", "premise", [T]),
        _cq("veracity", "Is there reason to think S is not reporting what S believes?", "exception", "inference", [T]),
        _cq("objectivity", "Could S's expectations or interests have shaped what S perceived or recalled?", "exception", "inference", [T, SO]),
    ],
    sep=[T],
    stance="Schum's decomposition of credibility into veracity, objectivity and observational sensitivity "
           "is used directly: access covers sensitivity, the two exceptions cover the other two.",
))

_register(Scheme(
    name="document_record",
    title="Argument from a record",
    description="A tangible record (dataset, filing, measurement, document) states the claim.",
    premises=["Record R is authentic", "R is accurate for the quantity or fact at issue", "R states A"],
    conclusion="A is plausibly true",
    default_strength="strong",
    critical_questions=[
        _cq("authentic", "Is R what it purports to be, from the stated origin and unaltered?", "assumption", "premise", [EV]),
        _cq("accuracy", "Was the quantity measured or the fact recorded by a method adequate to the use being made of it?", "assumption", "premise", [EV, "Measurement in Science"]),
        _cq("reading", "Does R state A, or does A require an interpretation of R that could be contested?", "assumption", "inference", [EV]),
        _cq("definitions", "Are the definitions and units in R the same as those assumed in A?", "exception", "inference", [EV]),
        _cq("currency", "Has the fact changed since R was produced?", "exception", "conclusion", [EV]),
    ],
    sep=[EV],
    stance="Tangible evidence is credited by authenticity and accuracy rather than by the source's veracity, "
           "following Schum; the definitions question is the usual way such arguments fail in practice.",
))

# ---------------------------------------------------------------------------
# Inferential schemes
# ---------------------------------------------------------------------------

_register(Scheme(
    name="sign",
    title="Argument from sign",
    description="An observed indicator is generally associated with the claimed state of affairs.",
    premises=["Indicator I is observed", "I is generally a sign of A"],
    conclusion="A plausibly holds",
    default_strength="weak",
    critical_questions=[
        _cq("observed", "Was I in fact observed, reliably?", "assumption", "premise", [EV]),
        _cq("association", "How strong is the association between I and A; how often does I occur without A?", "assumption", "inference", [EV, CONF]),
        _cq("alternatives", "Is there another state of affairs that would also produce I here?", "exception", "inference", [AB]),
    ],
    sep=[EV, CONF],
    stance="Treated as a weak likelihood-ratio argument: the association question asks for the ratio in plain terms.",
))

_register(Scheme(
    name="statistical_generalization",
    title="Argument from a sample to a population",
    description="A property holds in a sample, so it plausibly holds in the population or future cases.",
    premises=["In sample X, proportion p has property F", "X is drawn from population P"],
    conclusion="About p of P has F",
    critical_questions=[
        _cq("representative", "Is X representative of P in the respects that bear on F: selection, coverage, time?", "assumption", "inference", [IL, PI]),
        _cq("size", "Is X large enough that p is stable, and is the uncertainty stated?", "assumption", "inference", [IL]),
        _cq("measurement", "Was F measured the same way across X and across the comparison periods?", "assumption", "premise", [EV, "Measurement in Science"]),
        _cq("reference_class", "Is P the right reference class for the claim being made, or has it been chosen to fit?", "exception", "inference", [IL]),
        _cq("stability", "Is there reason to think the process generating F has changed?", "exception", "conclusion", [PI]),
    ],
    sep=[IL, PI],
    stance="Enumerative induction is accepted as defeasible, with Hume's problem answered pragmatically: "
           "the stability question makes the uniformity assumption explicit and challengeable rather than hidden.",
))

_register(Scheme(
    name="cause_to_effect",
    title="Argument from cause to effect",
    description="A cause known to be present will plausibly produce its effect.",
    premises=["C occurred", "C generally causes E", "No interfering condition is known"],
    conclusion="E plausibly occurred or will occur",
    critical_questions=[
        _cq("occurred", "Did C occur, in the form the causal generalisation requires?", "assumption", "premise", [EV]),
        _cq("generalisation", "Is 'C causes E' established by intervention or well-identified evidence, not association alone?", "assumption", "inference", [CM, CF]),
        _cq("interference", "Is a condition present here that blocks or masks the effect?", "exception", "inference", [CM]),
        _cq("magnitude", "Is the effect large enough to matter for the claim as stated?", "exception", "conclusion", [CM]),
    ],
    sep=[CM, CF],
    stance="Woodward's interventionist account is adopted: a causal generalisation counts as established when "
           "the effect would change under an intervention on the cause, and association alone does not meet that bar.",
))

_register(Scheme(
    name="correlation_to_cause",
    title="Argument from correlation to cause",
    description="A correlation between A and B is explained by A causing B.",
    premises=["A and B are correlated", "The correlation is not explained by chance, confounding, selection or reverse causation"],
    conclusion="A plausibly causes B",
    default_strength="weak",
    critical_questions=[
        _cq("real", "Is the correlation real: adequate sample, not an artefact of measurement or aggregation?", "assumption", "premise", [IL]),
        _cq("confounding", "Has a common cause of A and B been ruled out or adjusted for?", "assumption", "inference", [CM]),
        _cq("direction", "Could B cause A, or could the two be jointly caused by the way cases were selected?", "assumption", "inference", [CM, CF]),
        _cq("mechanism", "Is there a plausible mechanism from A to B, and does its timing fit?", "exception", "inference", [CM]),
        _cq("dose", "Does B vary with the degree of A, as a causal relation would predict?", "exception", "conclusion", [CM]),
    ],
    sep=[CM, CF, IL],
    stance="Strength defaults to weak and is upgraded only through the Evaluate step when the assumptions are "
           "discharged with interventional or quasi-experimental evidence; Pearl's ladder orders that evidence.",
))

_register(Scheme(
    name="best_explanation",
    title="Inference to the best explanation",
    description="Among the candidate explanations of the observations, this one explains them best.",
    premises=["Observations O", "Hypothesis H explains O", "No rival explains O as well"],
    conclusion="H is plausibly true",
    critical_questions=[
        _cq("explains", "Does H in fact account for O, including the parts of O that are awkward for it?", "assumption", "inference", [AB]),
        _cq("rivals", "Were the rivals considered genuinely the live ones, including the null and the mundane explanation?", "assumption", "inference", [AB]),
        _cq("comparison", "Is H better on explanatory grounds, or merely more familiar or more interesting?", "assumption", "inference", [AB, "Simplicity"]),
        _cq("prior", "Is H independently implausible, so that its explanatory fit is outweighed?", "exception", "conclusion", [AB, "Bayesian Epistemology"]),
        _cq("bad_lot", "Could the true explanation be one nobody has formulated?", "exception", "conclusion", [AB]),
    ],
    sep=[AB],
    stance="Lipton's distinction between the likeliest and the loveliest explanation is kept as the comparison "
           "question; van Fraassen's bad-lot objection is kept as an exception so that it can be raised without "
           "blocking every abductive argument.",
))

_register(Scheme(
    name="analogy",
    title="Argument from analogy",
    description="A case similar in relevant respects had the property, so this case plausibly does too.",
    premises=["Case X has property F", "Case Y is similar to X in respects R", "R is relevant to F"],
    conclusion="Y plausibly has F",
    default_strength="weak",
    critical_questions=[
        _cq("similar", "Are X and Y similar in the respects that actually bear on F?", "assumption", "inference", [AN]),
        _cq("relevant", "Is there a reason, not just a resemblance, why R should carry F across?", "assumption", "inference", [AN]),
        _cq("differences", "Are there differences between X and Y that bear on F?", "exception", "inference", [AN]),
        _cq("counter", "Is there a case similar in R that lacks F?", "exception", "conclusion", [AN]),
    ],
    sep=[AN],
    stance="Analogies are admitted as generators of hypotheses and as weak support; the 'relevant' question "
           "demands the articulation Bartha's account of analogical arguments requires.",
))

_register(Scheme(
    name="consequences",
    title="Argument from consequences",
    description="An option should or should not be taken because of what would follow from it.",
    premises=["If option X is taken, consequence K will follow", "K is good (or bad)"],
    conclusion="X should (or should not) be taken",
    critical_questions=[
        _cq("follows", "How strong is the evidence that K follows from X?", "assumption", "inference", [CM, CONF]),
        _cq("valued", "Is K good or bad by the standard the question actually uses?", "assumption", "premise", ["Value Theory"]),
        _cq("other_consequences", "Are there other consequences of X that point the other way?", "exception", "conclusion", ["Decision Theory"]),
        _cq("alternatives", "Is there an alternative to X with better consequences?", "exception", "conclusion", ["Decision Theory"]),
    ],
    sep=["Decision Theory", "Practical Reason"],
    stance="Used for evaluative and design issues only; the harness keeps the empirical question of what follows "
           "separate from the evaluative question of whether it is good, as the two assumptions.",
))

_register(Scheme(
    name="definition_classification",
    title="Argument from definition to classification",
    description="A thing meets the definition of a category, so it belongs to the category.",
    premises=["Category K is defined by conditions D", "Thing t satisfies D"],
    conclusion="t is a K",
    critical_questions=[
        _cq("definition", "Is D the accepted definition of K in the relevant practice, or one chosen to fit?", "assumption", "premise", ["Definitions"]),
        _cq("satisfies", "Does t satisfy each condition in D, on the evidence?", "assumption", "premise", [EV]),
        _cq("borderline", "Is t a borderline case where the definition does not settle membership?", "exception", "inference", ["Vagueness"]),
    ],
    sep=["Definitions"],
    stance="Needed for conceptual questions, where most of the work is fixing what is being asked.",
))

_register(Scheme(
    name="model_output",
    title="Argument from a model or simulation",
    description="A model, when run on sourced inputs, produces the claimed result.",
    premises=["Model M is validated for the regime in question", "Inputs were taken from identified sources", "M's output is A"],
    conclusion="A plausibly holds",
    critical_questions=[
        _cq("validated", "Has M been validated for this regime: scale, time period, population, intervention type?", "assumption", "premise", [MS, CS]),
        _cq("inputs", "Are the inputs sourced, and do they carry their own credentials?", "assumption", "premise", [CS, EV]),
        _cq("reproducible", "Is the run recorded well enough to reproduce: version, parameters, seed?", "assumption", "premise", [CS]),
        _cq("sensitivity", "Does A survive plausible variation of the uncertain parameters?", "assumption", "inference", [MS, CS]),
        _cq("structure", "Does M omit a mechanism that matters for A?", "exception", "inference", [MS]),
        _cq("idealisation", "Does an idealisation in M bear directly on A?", "exception", "inference", [MS]),
    ],
    sep=[MS, CS],
    stance="Models are instruments that produce evidence, not oracles; a model result enters the graph as "
           "model_output evidence whose credentials are the model's validation and provenance.",
))

_register(Scheme(
    name="attack",
    title="Attack",
    description="Generic scheme for attack arguments; the attack type carries the meaning.",
    premises=["Grounds for the attack"],
    conclusion="The target does not hold / does not apply",
    critical_questions=[
        _cq("grounds", "Are the grounds for the attack themselves evidenced?", "assumption", "premise", [DR, AA]),
    ],
    sep=[DR, AA],
    stance="An attack with no grounds is a bare denial and is inapplicable; stating this as an assumption keeps "
           "critics honest without blocking legitimate objections.",
))


def scheme(name: str) -> Scheme:
    return SCHEMES[name]


def list_schemes() -> list[str]:
    return list(SCHEMES)
