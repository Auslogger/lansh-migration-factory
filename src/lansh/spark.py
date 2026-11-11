"""
The one Spark session builder every part of LANSH uses.

Every session has Delta enabled, a UTC session time zone, ANSI mode on and a small number
of partitions. Spark, Delta and saspy all run on Java 21 (plan decision L4).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from lansh.config import env

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

log = logging.getLogger(__name__)

JAVA_MAJOR = 21
_KNOWN_JAVA21_HOMES = (
    "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home",
    "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home",
    "/usr/lib/jvm/java-21-openjdk-amd64",
    "/usr/lib/jvm/java-21-openjdk-arm64",
    "/usr/lib/jvm/java-21-openjdk",
    "/usr/lib/jvm/temurin-21-jdk-amd64",
)


def java_major_version(java_home: str | Path) -> int | None:
    """
    Read the major Java version from ``$JAVA_HOME/release``.

    It is the leading number of ``JAVA_VERSION``, except that Java 8 and older number
    themselves ``1.x``: ``1.8.0_392`` reads as 8.

    Args:
        java_home: A JDK home directory.

    Returns:
        The major version, such as 21, or None if the file or its ``JAVA_VERSION`` is
        missing.
    """
    release = Path(java_home) / "release"
    if not release.exists():
        return None
    text = release.read_text(encoding="utf-8", errors="replace")
    match = re.search(r'JAVA_VERSION="([0-9]+)(?:\.([0-9]+))?', text)
    if not match:
        return None
    major, minor = match.groups()
    return int(minor) if major == "1" and minor else int(major)


def ensure_java21() -> str | None:
    """
    Point ``JAVA_HOME`` at Java 21 before the JVM starts.

    The candidates, in order: ``LANSH_JAVA_HOME`` (which may come from ``.env``), the
    current ``JAVA_HOME``, then the known install locations. The first that is Java 21
    wins. If none is, a warning is logged and ``JAVA_HOME`` is left as it was.

    Returns:
        The Java 21 home now in ``JAVA_HOME``, or None if none was found.
    """
    candidates = [env("LANSH_JAVA_HOME"), os.environ.get("JAVA_HOME"), *_KNOWN_JAVA21_HOMES]
    for home in candidates:
        if home and java_major_version(home) == JAVA_MAJOR:
            os.environ["JAVA_HOME"] = home
            return home
    log.warning(
        "Java %s not found; Spark will use JAVA_HOME=%s", JAVA_MAJOR, os.environ.get("JAVA_HOME")
    )
    return None


def _sql_settings(shuffle_partitions: int) -> dict[str, str]:
    """
    List the runtime SQL settings every session gets: UTC, ANSI on and few shuffle partitions.
    """
    return {
        "spark.sql.session.timeZone": "UTC",
        # never switch ANSI off to silence an error: it would hide real differences (AGENTS.md)
        "spark.sql.ansi.enabled": "true",
        "spark.sql.shuffle.partitions": str(shuffle_partitions),
    }


def get_spark(app_name: str = "lansh", shuffle_partitions: int = 4) -> SparkSession:
    """
    Return the shared local Spark session, creating it on first use.

    The settings apply only when the session is created. Spark's builder would apply a later
    call's runtime SQL settings to the shared session, changing the shuffle partitions for
    every user of it (checked on Spark 4.2). So a later call returns the existing session
    unchanged, and logs a warning when the session's settings differ from those it asked for.

    Args:
        app_name: Spark application name, used when the session is created.
        shuffle_partitions: Shuffle partitions and default parallelism, used when the
            session is created.

    Returns:
        The shared SparkSession.
    """
    # deferred so that importing this module doesn't load PySpark
    from pyspark.errors import PySparkRuntimeError
    from pyspark.sql import SparkSession

    try:
        existing = SparkSession.active()
    except PySparkRuntimeError:  # no session yet
        existing = None
    if existing is not None:
        wanted = _sql_settings(shuffle_partitions)
        has = {key: existing.conf.get(key) for key in wanted}
        if has != wanted:
            log.warning(
                "the shared Spark session is returned unchanged: it has %s, not %s",
                {k: v for k, v in has.items() if v != wanted[k]},
                {k: v for k, v in wanted.items() if v != has[k]},
            )
        return existing

    ensure_java21()
    from delta import configure_spark_with_delta_pip

    builder = (
        SparkSession.builder.master("local[2]")
        .appName(app_name)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog"
        )
        .config(map=_sql_settings(shuffle_partitions))
        .config("spark.default.parallelism", str(shuffle_partitions))
        .config("spark.ui.enabled", "false")
        .config("spark.driver.memory", "2g")
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark
