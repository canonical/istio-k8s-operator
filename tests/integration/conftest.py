# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import functools
import logging
import os
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


class Store(defaultdict):
    def __init__(self):
        super(Store, self).__init__(Store)

    def __getattr__(self, key):
        """Override __getattr__ so dot syntax works on keys."""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        """Override __setattr__ so dot syntax works on keys."""
        self[key] = value


store = Store()


def timed_memoizer(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fname = func.__qualname__
        logger.info("Started: %s" % fname)
        start_time = datetime.now()
        if fname in store.keys():
            ret = store[fname]
        else:
            logger.info("Return for {} not cached".format(fname))
            ret = await func(*args, **kwargs)
            store[fname] = ret
        logger.info("Finished: {} in: {} seconds".format(fname, datetime.now() - start_time))
        return ret

    return wrapper


@pytest.fixture(scope="module")
@timed_memoizer
async def istio_core_charm(ops_test):
    count = 0
    while True:
        try:
            return await ops_test.build_charm(".", verbosity="debug")
        except RuntimeError:
            logger.warning("Failed to build charm. Trying again!")
            count += 1

            if count == 3:
                raise


@pytest.fixture(scope="module")
@timed_memoizer
async def istio_metadata_requirer_charm(ops_test: OpsTest):
    charm_path = (Path(__file__).parent / "testers" / "istio-metadata-requirer").absolute()

    # Update libraries in the tester charms
    root_lib_folder = Path(__file__).parent.parent.parent / "lib"
    tester_lib_folder = charm_path / "lib"

    if os.path.exists(tester_lib_folder):
        shutil.rmtree(tester_lib_folder)
    shutil.copytree(root_lib_folder, tester_lib_folder)

    return await ops_test.build_charm(charm_path, verbosity="debug")
