#!/usr/bin/env python3
"""
tools/setup_jars.py

Downloads Debezium 3.0+ JARs using direct zip archive download or Maven,
and installs them into the pydbzengine package so Connect-mode works.

Usage:
    python tools/setup_jars.py
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

DEBEZIUM_VERSION = "3.0.0.Final"
PYDBZENGINE_MIN_VERSION = "3.4.1.0"
COMMON_ZIP_URL = f"https://repo1.maven.org/maven2/io/debezium/debezium-embedded/{DEBEZIUM_VERSION}/debezium-embedded-{DEBEZIUM_VERSION}-embedded-common.zip"


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
            "      <version>${debezium.version}</version>\n"
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


def run_mvn(cmd: str, cwd: Path) -> bool:
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}", file=sys.stderr)
        return False
    if result.stdout:
        print(result.stdout[-2000:])  # last 2 KB
    return True


def download_zip(url: str, dest_dir: Path) -> bool:
    """Download and extract pre-packaged Debezium Embedded zip archive."""
    print(f"Downloading pre-packaged Debezium archive: {url}")
    zip_path = dest_dir / "debezium-common.zip"
    try:
        urllib.request.urlretrieve(url, zip_path)
        print("[OK] Download complete. Extracting JARs...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(dest_dir)
        zip_path.unlink()
        return True
    except Exception as e:
        print(f"[FAILED] ZIP download failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(
        description="Downloads Debezium JARs and installs them into the pydbzengine package."
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
    parser.add_argument(
        "--use-maven", action="store_true", help="Force using local Maven CLI instead of direct ZIP download"
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

    # 1. Locate pydbzengine
    print("\n[1/4] Locating pydbzengine installation...")
    try:
        import pydbzengine

        target = Path(pydbzengine.__file__).parent / "debezium" / "libs"
        print(f"[OK] pydbzengine found at: {Path(pydbzengine.__file__).parent}")
    except ImportError:
        print(f"[FAILED] pydbzengine not installed: pip install pydbzengine>={PYDBZENGINE_MIN_VERSION}", file=sys.stderr)
        sys.exit(1)

    tmp_dir = Path(__file__).parent / "_jar_download_tmp"
    tmp_dir.mkdir(exist_ok=True)
    out_dir = tmp_dir / "libs"
    out_dir.mkdir(exist_ok=True)

    # 2. Try direct ZIP download if using default version & no explicit --use-maven
    downloaded = False
    if not args.use_maven and version == DEBEZIUM_VERSION:
        print("\n[2/4] Attempting direct ZIP download (Zero-Maven mode)...")
        if download_zip(COMMON_ZIP_URL, out_dir):
            downloaded = True

    if not downloaded:
        print("\n[2/4] Checking Maven fallback...")
        r = subprocess.run("mvn --version", shell=True, capture_output=True, text=True)
        if r.returncode != 0:
            print("[FAILED] Maven not found and direct ZIP download unavailable. Please install Maven.", file=sys.stderr)
            sys.exit(1)
        print("[OK] Maven found")

        pom_path = tmp_dir / "pom.xml"
        pom_content = generate_pom_content(version, connectors)
        pom_path.write_text(pom_content, encoding="utf-8")

        print(f"\n[3/4] Downloading Debezium {version} JARs via Maven...")
        if not run_mvn(
            f'mvn -f "{pom_path}" dependency:copy-dependencies -DoutputDirectory="{out_dir}"',
            cwd=tmp_dir,
        ):
            print("Download failed.", file=sys.stderr)
            sys.exit(1)

    # 4. Copy JARs (clean old ones first)
    print(f"\n[4/4] Installing JARs to {target}...")
    if target.exists():
        old = list(target.glob("*.jar"))
        if old:
            print(f"  Removing {len(old)} old JARs...")
            for j in old:
                j.unlink()

    target.mkdir(parents=True, exist_ok=True)
    jars = list(out_dir.glob("*.jar")) + list(out_dir.rglob("*.jar"))
    jars = list(dict.fromkeys(jars)) # deduplicate
    for jar in jars:
        shutil.copy2(jar, target)

    # Cleanup
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n{'=' * 70}")
    print(f"SUCCESS — installed {len(jars)} JARs to {target}")
    print("=" * 70)
    print("\nNow run Connect mode:")
    print("  python examples/rag_chatbot/main.py")


if __name__ == "__main__":
    main()
