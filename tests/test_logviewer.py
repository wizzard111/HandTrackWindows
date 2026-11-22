from handtrack import logviewer


def test_format_colours_by_level_and_source():
    line = "2026-11-22 13:52:15,123 | {lvl} | {thread} | hello"
    assert logviewer._format(line.format(lvl="INFO", thread="MainThread")) == \
        "\x1b[97m13:52:15  INFO     hello\x1b[0m"
    assert logviewer._format(line.format(lvl="WARNING", thread="Engine")).startswith("\x1b[93m")
    assert logviewer._format(line.format(lvl="ERROR", thread="Engine")).startswith("\x1b[91m")
    assert logviewer._format(line.format(lvl="INFO", thread="NativeOutput")).startswith("\x1b[90m")
    assert logviewer._format("a traceback line") == "a traceback line"


def test_bad_arguments_do_not_crash():
    assert logviewer.main([]) in (1, 2)
