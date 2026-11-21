from red_on_logic.cli import main


def test_skeleton_exits_2() -> None:
    assert main([]) == 2
