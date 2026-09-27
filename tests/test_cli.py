from open_ost2pst.cli import build_parser


def test_inspect_command_parses() -> None:
    args = build_parser().parse_args(["inspect", "mailbox.ost", "--json"])

    assert args.command == "inspect"
    assert args.source.name == "mailbox.ost"
    assert args.as_json is True


def test_convert_command_parses() -> None:
    args = build_parser().parse_args(["convert", "source.ost", "target.pst"])

    assert args.command == "convert"
    assert args.source.name == "source.ost"
    assert args.destination.name == "target.pst"
