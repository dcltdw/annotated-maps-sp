from pathlib import Path

from token_usage import tally, transcript_dir_for, usage_of


def _rec(message_id, output, cache_write=0, fresh_input=0, cache_read=0):
    return {
        "message": {
            "id": message_id,
            "usage": {
                "output_tokens": output,
                "cache_creation_input_tokens": cache_write,
                "input_tokens": fresh_input,
                "cache_read_input_tokens": cache_read,
            },
        }
    }


def test_tally_sums_output_and_cache_write():
    totals = tally([_rec("a", 10, cache_write=5), _rec("b", 20, cache_write=7)])
    assert totals["output"] == 30
    assert totals["cache_write"] == 12
    assert totals["turns"] == 2


def test_dedupes_by_message_id_keeping_the_largest_output():
    # a streaming partial followed by the final message for the same id
    totals = tally([_rec("a", 5, cache_write=2), _rec("a", 18, cache_write=9)])
    assert totals["output"] == 18
    assert totals["cache_write"] == 9
    assert totals["turns"] == 1


def test_skips_records_without_a_usage_block():
    totals = tally([{"type": "user", "message": {"content": "hi"}}, _rec("a", 4)])
    assert totals["output"] == 4
    assert totals["turns"] == 1


def test_counts_records_without_ids_separately():
    totals = tally([{"usage": {"output_tokens": 3}}, {"usage": {"output_tokens": 4}}])
    assert totals["output"] == 7
    assert totals["turns"] == 2


def test_usage_of_reads_top_level_or_nested_usage():
    assert usage_of({"usage": {"output_tokens": 1}}) == (None, {"output_tokens": 1})
    assert usage_of({"message": {"content": "x"}}) is None


def test_transcript_dir_mangles_the_project_path():
    directory = transcript_dir_for(Path("/Users/x/Github/annotated-maps-sp"))
    assert directory.name == "-Users-x-Github-annotated-maps-sp"
    assert directory.parent.name == "projects"
