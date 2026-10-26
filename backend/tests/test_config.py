from footballiq import config


def test_load_dotenv_sets_missing_keys_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nexport FIQ_A="quoted value"\nFIQ_B=plain # trailing comment\nFIQ_C=\nFIQ_D=keep\nnot a line\n')
    monkeypatch.delenv("FIQ_A", raising=False)
    monkeypatch.delenv("FIQ_B", raising=False)
    monkeypatch.delenv("FIQ_C", raising=False)
    monkeypatch.setenv("FIQ_D", "from-environment")
    loaded = config.load_dotenv(env)
    import os
    assert sorted(loaded) == ["FIQ_A", "FIQ_B"]
    assert os.environ["FIQ_A"] == "quoted value" and os.environ["FIQ_B"] == "plain"
    assert os.environ["FIQ_D"] == "from-environment" and "FIQ_C" not in os.environ
    for k in loaded:
        monkeypatch.delenv(k)


def test_load_dotenv_missing_file_is_a_no_op(tmp_path):
    assert config.load_dotenv(tmp_path / "nope.env") == []
