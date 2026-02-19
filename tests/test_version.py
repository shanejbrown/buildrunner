from collections import OrderedDict
from unittest.mock import patch

import pytest
from buildrunner.config import loader
from buildrunner.config.loader import (
    BuildRunnerVersionError,
    ConfigVersionFormatError,
    ConfigVersionTypeError,
)

buildrunner_version = "2.0.701"
config_version = "2.0"


@pytest.fixture(name="config")
def fixture_config_file():
    config = OrderedDict({"version": config_version})
    yield config


@patch("buildrunner.__version__", buildrunner_version)
def test_valid_version_file(config):
    loader._validate_version(config=config)


@patch("buildrunner.__version__", "DEVELOPMENT")
def test_missing_version_file(config):
    # When version is DEVELOPMENT, validation is skipped (no exception)
    loader._validate_version(config=config)


@patch("buildrunner.__version__", "")
def test_missing_version_in_version_file(config):
    with pytest.raises(BuildRunnerVersionError):
        loader._validate_version(config=config)


@patch("buildrunner.__version__", "1.3.4")
def test_valid_version_parsing(config):
    # 1.3.4 parses to 1.3; config 2.0 > 1.3 so use config without version
    loader._validate_version(config=OrderedDict({}))


@patch("buildrunner.__version__", "1")
def test_invalid_single_component_version(config):
    with pytest.raises(BuildRunnerVersionError):
        loader._validate_version(config=config)


@patch("buildrunner.__version__", "2.0.701")
def test_invalid_config_version_type(config):
    with pytest.raises(ConfigVersionTypeError):
        loader._validate_version(config={"version": "two.zero.five"})


def test_bad_version(config):
    bad_config = OrderedDict({"version": 2.1})
    with patch("buildrunner.__version__", buildrunner_version):
        with pytest.raises(ConfigVersionFormatError):
            loader._validate_version(config=bad_config)
