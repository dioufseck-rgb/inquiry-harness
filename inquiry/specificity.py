"""Provider-independent checks for answer-sized claim proposals."""
from __future__ import annotations
import re


def _canonical(text: str) -> str:
    text = text.casefold()
    for pattern, replacement in ((r"\bmilligrams?\b", "mg"), (r"\bmicrograms?\b", "mcg"),
                                 (r"\bequally\b", "equal"), (r"\bweight(?:ed|ing|s)\b", "weight"),
                                 (r"\byears\b", "year"), (r"\bmonths\b", "month")):
        text = re.sub(pattern, replacement, text)
    return re.sub(r"[^a-z0-9µμ]+", "", text)


def protocol_details(text: str) -> list[tuple[str, str]]:
    details = []
    dose = re.compile(r"\b\d+(?:\.\d+)?(?:\s*[–-]\s*\d+(?:\.\d+)?)?\s*(?:mg|mcg|µg|μg|g|ml|milligrams?|micrograms?)\b", re.I)
    for match in dose.finditer(text):
        tail = text[match.end():]
        if re.match(r"\s*(?:/\s*(?:m[23³²]?|l|km)\b|per\s+(?:cubic|square|lit(?:re|er)|kilomet))", tail, re.I):
            continue  # concentration/emission units are not a medication dose
        details.append(("dose", match[0]))
    patterns = {
        "endpoint_definition": r"\b(?:composite|endpoint|outcome)\s+(?:of|includes|compris\w*|defined\s+as)|\bfirst[- ](?:occurrence|person[- ]event|event)\s+(?:of|composite)|\b(?:union|deduplicated)\s+(?:of|composite)",
        "weighting_rule": r"\bequal(?:ly)?[- ]weight(?:ed|ing|s)?\b|\bseverity[- ]weight(?:ed|ing)\b|\bweights?\s+(?:each|every)\b|\bcounts?\s+(?:each|every).{0,35}\bonce\b",
        "fixed_baseline": r"\b(?:baseline|relative to|compared (?:with|to))\s+(?:from\s+|in\s+|the\s+)?(?:[A-Za-z]+\s+)?(?:19|20)\d{2}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?\b",
        "followup_window": r"\b(?:over|within|after|at|for|during)\s+(?:(?:about|roughly|the first|first)\s+)?(?:\d+(?:\.\d+)?(?:\s*[–-]\s*\d+(?:\.\d+)?)?|one|two|three|four|five|six|seven|eight|nine|ten)\s*(?:years?|months?|weeks?|days?)\b",
    }
    for kind, pattern in patterns.items():
        for match in re.finditer(pattern, text, re.I):
            if kind == "followup_window" and re.search(r"\b(?:aged?|adults?|people|participants?|patients?)\s*$", text[:match.start()], re.I):
                continue
            detail = match[0]
            if kind == "endpoint_definition":
                tail = text[match.start():]
                detail = re.split(r"[.;](?:\s|$)", tail, maxsplit=1)[0][:180]
            details.append((kind, detail))
    return details


def claim_specificity_errors(text: str, answerhood: str, *, size_limits: bool = True,
                             scope=None, issue_scope=None) -> list[str]:
    errors = []
    if size_limits and len(text) > 250:
        errors.append(f"length {len(text)} exceeds 250 characters")
    digits = sum(ch.isdigit() for ch in text)
    if size_limits and digits > 8:
        errors.append(f"digit count {digits} exceeds 8")
    anchor = _canonical(answerhood)
    if scope is not None and issue_scope is not None:
        from .argument.scope import within
        for field in ("population", "period"):
            if not within(scope, issue_scope, field):
                errors.append(f"{field} is not equal to or narrower than the issue scope")
        anchor = _canonical(" ".join(getattr(issue_scope, k) for k in ("population", "comparison", "outcome", "period")))
    for kind, detail in protocol_details(text):
        if _canonical(detail) not in anchor:
            errors.append(f"{kind} not specified in answerhood: {detail}")
    return errors


def source_answerhood(question: str, answerhood: str) -> tuple[str, list[str]]:
    """A frame may not impose an unrequested protocol on future evidence."""
    reasons = claim_specificity_errors(answerhood, question, size_limits=False)
    if re.search(r"\bspecified\s+(?:time horizon|follow.up|window)|\bexplicit\s+(?:endpoint|severity.weighting)", answerhood, re.I):
        reasons.append("answerhood imposes a measurement protocol rather than source-reported measures")
    if re.search(r"\bunweighted composite|\bexplicit severity weights|\boverlapping events are counted", answerhood, re.I) and not re.search(
            r"\bcomposite|\bweights?|\bcounting", question, re.I):
        reasons.append("answerhood requests an endpoint construction absent from the original question")
    if reasons:
        return ("Report what sources establish about this issue, using their outcome measures and reporting periods. "
                "State direction or source-reported magnitude, population, and uncertainty."), reasons
    return answerhood, []
