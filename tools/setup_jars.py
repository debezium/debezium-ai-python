#!/usr/bin/env python3
"""
tools/setup_jars.py

Downloads Debezium 3.0+ JARs using Maven and installs them into the
pydbzengine package so Connect-mode (EngineFormat.CONNECT) works.

Ported from PR #400 debezium-python/setup_jars.py.

Usage:
    python tools/setup_jars.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

POM_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
             http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.debezium.pydebeziumai</groupId>
  <artifactId>jar-downloader</artifactId>
  <version>1.0-SNAPSHOT</version>
  <properties>
    <debezium.version>3.0.0.Final</debezium.version>
    <maven.compiler.source>17</maven.compiler.source>
    <maven.compiler.target>17</maven.compiler.target>
  </properties>
  <dependencies>
    <dependency>
      <groupId>io.debezium</groupId>
      <artifactId>debezium-embedded</artifactId>
      <version>${debezium.version}</version>
    </dependency>
    <dependency>
      <groupId>io.debezium</groupId>
      <artifactId>debezium-connector-postgres</artifactId>
      <version>${debezium.version}</version>
    </dependency>
  </dependencies>
</project>"""


def run(cmd: str, cwd: Path) -> bool:
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}")
        return False
    if result.stdout:
        print(result.stdout[-2000:])  # last 2 KB
    return True


def main() -> None:
    print("=" * 70)
    print("PyDebeziumAI — Debezium JAR Setup (Connect mode)")
    print("=" * 70)

    # 1. Check Maven
    print("\n[1/5] Checking Maven...")
    r = subprocess.run("mvn --version", shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        print("Maven not found.\n  sudo apt update && sudo apt install maven")
        sys.exit(1)
    print("✓ Maven found")

    # 2. Write a temp pom.xml
    tmp_dir = Path(__file__).parent / "_jar_download_tmp"
    tmp_dir.mkdir(exist_ok=True)
    pom_path = tmp_dir / "pom.xml"
    pom_path.write_text(POM_CONTENT, encoding="utf-8")
    print(f"\n[2/5] Written temp pom.xml → {pom_path}")

    # 3. Download JARs
    out_dir = tmp_dir / "libs"
    print("\n[3/5] Downloading Debezium 3.0.0.Final JARs...")
    if not run(
        f'mvn -f "{pom_path}" dependency:copy-dependencies -DoutputDirectory="{out_dir}"',
        cwd=tmp_dir,
    ):
        print("Download failed.")
        sys.exit(1)

    # 4. Find pydbzengine
    print("\n[4/5] Locating pydbzengine installation...")
    try:
        import pydbzengine

        target = Path(pydbzengine.__file__).parent / "debezium" / "libs"
        print(f"✓ pydbzengine at: {Path(pydbzengine.__file__).parent}")
    except ImportError:
        print("pydbzengine not installed: pip install pydbzengine>=3.4.1.0")
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
