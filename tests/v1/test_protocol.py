import pytest

from inquiry.v1.protocol import OutputProtocolError, parse_single_json_object


# Exact worker_output.reply from requested-20261114/question_004-baseline,
# ledger sequence 2. The former extractor admitted the first open and silently
# discarded the remaining two complete operations.
SAVED_PROPOSER_REPLY = (
    '{"operation":"open","arguments":{"source_id":"doc_001","version":"1.0"}}'
    '{"operation":"open","arguments":{"source_id":"doc_003","version":"1.0"}}'
    '{"operation":"open","arguments":{"source_id":"doc_001","version":"1.0"}}'
)

# Minimized from the same run, sequence 13: two request-shaped objects preceded
# a critique envelope. Its first object was previously treated as an empty
# critique. The substantive critique is immaterial to the framing regression.
SAVED_CRITIC_FRAMING = (
    '{"source_id":"doc_003","version":"1.0"}'
    '{"source_id":"doc_002","version":"1.0"}'
    '{"observations":["Examine the missing source"],"attacks":{}}'
)


@pytest.mark.parametrize("reply", [SAVED_PROPOSER_REPLY, SAVED_CRITIC_FRAMING])
def test_saved_multiobject_failure_cannot_silently_select_the_first_object(reply):
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object(reply)
    assert exc.value.code == "trailing_data"
    assert "exactly one JSON object" in str(exc.value)


@pytest.mark.parametrize("reply,expected", [
    ("{}", {}),
    (' \t\n {"operation":"open","arguments":{"source_id":"source"}} \r\n',
     {"operation": "open", "arguments": {"source_id": "source"}}),
    ('{"text":"Braces { } and escaped quotes \\\" are content", "values":[1, 2.5, null, true]}',
     {"text": 'Braces { } and escaped quotes " are content', "values": [1, 2.5, None, True]}),
    ('{"outer":{"one":{"key":1},"two":{"key":2}}}', {"outer": {"one": {"key": 1}, "two": {"key": 2}}}),
    ('{"small":1e-300,"negative_zero":-0.0}', {"small": 1e-300, "negative_zero": -0.0}),
])
def test_complete_single_object_and_json_whitespace_are_accepted(reply, expected):
    assert parse_single_json_object(reply) == expected


@pytest.mark.parametrize("reply", [
    '{}{}', '{} \n {"second": true}', '{} true', '{} []', '{} // comment', '{} trailing',
])
def test_every_trailing_value_or_junk_is_rejected(reply):
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object(reply)
    assert exc.value.code == "trailing_data"


@pytest.mark.parametrize("reply", [
    'Here is the JSON: {}', '```json\n{}\n```', '```\n{}\n```',
    '\ufeff{}', '\u00a0{}', '{"operation":', '{"graph":{"id":"truncated"}',
    '{"operation" "submit"}', '{"operation":"submit",}', '{"number":01}',
])
def test_prose_fences_non_json_whitespace_and_malformed_objects_are_rejected(reply):
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object(reply)
    assert exc.value.code == "invalid_json"


@pytest.mark.parametrize("reply", ['[]', '[{}]', 'null', 'true', 'false', '1', '1.5', '"{}"'])
def test_other_top_level_json_types_are_not_worker_envelopes(reply):
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object(reply)
    assert exc.value.code == "nonobject_reply"


@pytest.mark.parametrize("reply", [
    '{"operation":"open","operation":"finish"}',
    '{"graph":{"scope":{"population":"narrow","population":"wide"}}}',
    '{"records":[{"id":"one","id":"two"}]}',
    '{"id":"one","\\u0069d":"two"}',
    # Reduced from requested-20261114/question_003-baseline sequence 29.
    # Identical duplicate values are still ambiguous framing, not an exception.
    '{"graph":{"revision":2,"revision":2}}',
])
def test_duplicate_keys_at_every_depth_are_rejected_instead_of_overwritten(reply):
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object(reply)
    assert exc.value.code == "duplicate_key"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e9999", "-1e9999"])
def test_nonfinite_values_and_float_overflow_are_rejected(value):
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object('{"nested":[{"value":' + value + '}]}')
    assert exc.value.code == "nonfinite_number"


@pytest.mark.parametrize("reply", ["", " \t\r\n"])
def test_empty_reply_is_explicit(reply):
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object(reply)
    assert exc.value.code == "empty_reply"


@pytest.mark.parametrize("reply", [None, {}, b"{}", ["{}"]])
def test_nontext_reply_is_explicit(reply):
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object(reply)
    assert exc.value.code == "nontext_reply"


def test_error_message_does_not_copy_raw_response_fragments():
    with pytest.raises(OutputProtocolError) as exc:
        parse_single_json_object('{"PRIVATE_RESPONSE_SENTINEL":')
    assert "PRIVATE_RESPONSE_SENTINEL" not in str(exc.value)
    assert "character" in str(exc.value)
