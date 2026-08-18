#!/usr/bin/env bash
# cpp-hello build script (Linux / macOS)
set -e
cd "$(dirname "$0")"
mkdir -p bin

# prefer g++, then clang++
if command -v g++ >/dev/null 2>&1; then
    CXX=g++
elif command -v clang++ >/dev/null 2>&1; then
    CXX=clang++
else
    echo "[build] No C++ compiler found. Install g++ or clang++."
    exit 1
fi

echo "[build] $CXX detected, compiling..."
$CXX -std=c++17 -O2 -static -o bin/cpp-hello cpp-hello.cpp -lpthread
echo "[build] OK: bin/cpp-hello"
