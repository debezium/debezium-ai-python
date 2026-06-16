#!/usr/bin/env python3
"""
tools/setup_jars.py

Downloads Debezium 3.0+ JARs using Maven and installs them into the
pydbzengine package so Connect-mode (EngineFormat.CONNECT) works.

Usage:
    python tools/setup_jars.py
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEBEZIUM_VERSION = "3.5.0.Final"
PYDBZENGINE_MIN_VERSION = "3.4.1.0"


def generate_pom_content(version: str, connectors: list[str]) -> str:
    """Generate dynamic pom.xml content based on selected connectors."""
    dependencies = [
        "    <dependency>\n"
        "      <groupId>io.debezium</groupId>\n"
        "      <artifactId>debezium-embedded</artifactId>\n"
        "      <version>${debezium.version}</version>\n"
        "    </dependency>",
        "    <dependency>\n"
        "      <groupId>org.slf4j</groupId>\n"
        "      <artifactId>slf4j-simple</artifactId>\n"
        "      <version>1.7.36</version>\n"
        "    </dependency>",
    ]
    for conn in connectors:
        dependencies.append(
            "    <dependency>\n"
            "      <groupId>io.debezium</groupId>\n"
            f"      <artifactId>debezium-connector-{conn}</artifactId>\n"
            "      <version>${{debezium.version}}</version>\n"
            "    </dependency>"
        )

    dependencies_str = "\n".join(dependencies)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
             http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.debezium.pydebeziumai</groupId>
  <artifactId>jar-downloader</artifactId>
  <version>1.0-SNAPSHOT</version>
  <properties>
    <debezium.version>{version}</debezium.version>
    <maven.compiler.source>17</maven.compiler.source>
    <maven.compiler.target>17</maven.compiler.target>
  </properties>
  <dependencies>
{dependencies_str}
  </dependencies>
</project>"""


def run(cmd: str, cwd: Path) -> bool:
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}", file=sys.stderr)
        return False
    if result.stdout:
        print(result.stdout[-2000:])  # last 2 KB
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Downloads Debezium JARs using Maven and installs them into the pydbzengine package."
    )
    parser.add_argument(
        "--version", "-v", default=DEBEZIUM_VERSION, help=f"Debezium version to download (default: {DEBEZIUM_VERSION})"
    )
    parser.add_argument(
        "--connector",
        "-c",
        action="append",
        choices=["postgres", "mysql", "mongodb", "oracle", "sqlserver", "spanner"],
        help="Connector type(s) to download (default: postgres). Can be specified multiple times.",
    )
    args = parser.parse_args()

    version = args.version
    connectors = args.connector or ["postgres"]

    print("=" * 70)
    print("PyDebeziumAI — Debezium JAR Setup (Connect mode)")
    print("=" * 70)
    print(f"Target Debezium Version: {version}")
    print(f"Target Connector(s):     {', '.join(connectors)}")
    print("=" * 70)

    # 1. Check Maven
    print("\n[1/5] Checking Maven...")
    r = subprocess.run("mvn --version", shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print("Maven not found. Please install Maven on your system.", file=sys.stderr)
        sys.exit(1)
    print("✓ Maven found")

    # 2. Write a temp pom.xml
    tmp_dir = Path(__file__).parent / "_jar_download_tmp"
    tmp_dir.mkdir(exist_ok=True)
    pom_path = tmp_dir / "pom.xml"
    pom_content = generate_pom_content(version, connectors)
    pom_path.write_text(pom_content, encoding="utf-8")
    print(f"\n[2/5] Written temp pom.xml → {pom_path}")

    # 3. Download JARs
    out_dir = tmp_dir / "libs"
    print(f"\n[3/5] Downloading Debezium {version} JARs...")
    if not run(
        f'mvn -f "{pom_path}" dependency:copy-dependencies -DoutputDirectory="{out_dir}"',
        cwd=tmp_dir,
    ):
        print("Download failed.", file=sys.stderr)
        sys.exit(1)

    # 4. Find pydbzengine
    print("\n[4/5] Locating pydbzengine installation...")
    try:
        import pydbzengine

        target = Path(pydbzengine.__file__).parent / "debezium" / "libs"
        print(f"✓ pydbzengine at: {Path(pydbzengine.__file__).parent}")
    except ImportError:
        print(f"pydbzengine not installed: pip install pydbzengine>={PYDBZENGINE_MIN_VERSION}", file=sys.stderr)
        sys.exit(1)

    # 5. Copy JARs (clean old ones first)
    print(f"\n[5/5] Installing JARs to {target}...")
    if target.exists():
        old = list(target.glob("*.jar"))
        if old:
            print(f"  Removing {len(old)} old JARs...")
            for j in old:
                j.unlink()

    target.mkdir(parents=True, exist_ok=True)
    jars = list(out_dir.glob("*.jar"))
    for jar in jars:
        shutil.copy2(jar, target)

    # Cleanup
    shutil.rmtree(tmp_dir)

    print(f"\n{'=' * 70}")
    print(f"SUCCESS — installed {len(jars)} JARs to {target}")
    print("=" * 70)
    print("\nNow run Connect mode:")
    print("  python examples/rag_chatbot/main.py")


if __name__ == "__main__":
    main()
