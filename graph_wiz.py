from __future__ import annotations
import argparse
import configparser
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import List, Set
from urllib.parse import urlparse

SEMVER_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-.]+)?(?:\+[0-9A-Za-z-.]+)?$")
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_OUTPUT_EXTS = {'.png', '.svg', '.svgz'}
REPO_MODES = {'auto', 'local', 'git', 'http'}

def error(msg: str) -> None:

    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)

def validate_package_name(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("package name must not be empty")
    if not PACKAGE_NAME_RE.match(value):
        raise argparse.ArgumentTypeError("package name contains invalid characters")
    return value

def validate_repo(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in ('http', 'https', 'git', 'ssh'):
        if not parsed.netloc:
            raise argparse.ArgumentTypeError(f"repo URL looks invalid: {value}")
        return value
    if os.path.exists(value):
        return os.path.abspath(value)
    else:
        raise argparse.ArgumentTypeError(f"repo path does not exist: {value}")

def validate_repo_mode(value: str) -> str:
    v = value.lower()
    if v not in REPO_MODES:
        raise argparse.ArgumentTypeError(f"repo-mode must be one of: {', '.join(sorted(REPO_MODES))}")
    return v

def validate_version(value: str) -> str:
    if value == 'latest':
        return value
    if SEMVER_RE.match(value):
        return value
    raise argparse.ArgumentTypeError("version must be 'latest' or follow semantic versioning (e.g. 1.2.3)")

def validate_output(value: str) -> str:
    root, ext = os.path.splitext(value)
    if ext == '':
        raise argparse.ArgumentTypeError("output file must have an extension like .png or .svg")
    if ext.lower() not in VALID_OUTPUT_EXTS:
        raise argparse.ArgumentTypeError(f"unsupported output extension '{ext}'; supported: {', '.join(sorted(VALID_OUTPUT_EXTS))}")
    dirpath = os.path.dirname(value) or '.'
    if not os.path.isdir(dirpath):
        raise argparse.ArgumentTypeError(f"output directory does not exist: {dirpath}")
    test_path = os.path.join(dirpath, f".depviz_tmp_write_test_{os.getpid()}")
    try:
        with open(test_path, 'w') as f:
            f.write('x')
        os.remove(test_path)
    except Exception as e:
        raise argparse.ArgumentTypeError(f"no write permission in output directory '{dirpath}': {e}")
    return os.path.abspath(value)

def validate_filter(value: str) -> str:
    if value is None:
        return ''
    return value
def has_git() -> bool:
    try:
        subprocess.run(['git', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
def clone_repo(repo: str, dest: str, version: str |None = None) -> None:
    if not has_git():
        raise RuntimeError("Git is not installed or not found in PATH; cannot clone repository")
    cmd = ['git', 'clone','--depth', '1', repo, dest]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to clone repository '{repo}': {e}")
    if version and version != 'latest':
        try:
            subprocess.run(['git', 'checkout', version], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError as e:
            try:
                subprocess.run(['git','fetch','--tags'], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                subprocess.run(['git','checkout', version], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to checkout version '{version}' in repository '{repo}': {e}")
def prepare_repo(repo: str, repo_mode: str, version: str) -> str:
    parsed = urlparse(repo)
    is_url = parsed.scheme in ('http', 'https', 'git', 'ssh')
    tmpdir = tempfile.mkdtemp(prefix='depviz_repo_')
    try:
        if is_url:
            clone_repo(repo, tmpdir, version)
            return tmpdir
        else:
            abs_path=os.path.abspath(repo)
            if not os.path.isdir(abs_path):
                raise RuntimeError(f"Local repository path is not a directory: {abs_path}")
            shutil.copytree(abs_path, tmpdir, dirs_exist_ok=True)
            if os.path.isdir(os.path.join(tmpdir, '.git')):
                if version and version !='latest':
                    try:
                        subprocess.run(['git','checkout', version], cwd=tmpdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    except Exception:
                       pass
            return tmpdir
    except Exception:
        shutil.rmtree(tmpdir,ignore_errors=True)
        raise

def parse_requirements_file(req_file_path: str) -> Set[str]:
    dependencies = set()
    if not os.path.isfile(req_file_path):
        return dependencies
    with open(req_file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            pkg_name = re.split(r'[<>=!~]', line)[0].strip()
            if pkg_name:
                dependencies.add(pkg_name)
    return dependencies

def parse_setup_cfg(path: str) -> Set[str]:
    deps = set()
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding='utf-8')

    if cfg.has_section('options') and cfg.has_option('options', 'install_requires'):
        raw = cfg.get('options', 'install_requires')
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            pkg = re.split(r'[<>=!~]', line)[0].strip()
            if pkg:
                deps.add(pkg)
    return deps

def parse_pyproject_toml(path: str) -> Set[str]:
    text = open(path, 'r', encoding='utf-8').read()
    m = re.search(r"(?ms)^\s*\[project\].*?^dependencies\s*=\s*\[(.*?)\]", text)
    if m:
        inner = m.group(1)
        items = re.findall(r"['\"]([^'\"]+)['\"]", inner)
        return items
    m2 = re.search(r"(?ms)^\s*\[tool\.poetry\].*?^dependencies\s*=\s*\{(.*?)\}", text)
    if m2:
        block = m2.group(1)
        deps = []
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('=', 1)
            pkg_name = parts[0].strip().strip('"').strip("'")
            if pkg_name.lower() != 'python':
                deps.append(pkg_name)
        return deps
    m3 = re.search(r"(?ms)^\s*\[tool\.flit\.metadata\].*?^requires\s*=\s*\[(.*?)\]", text)
    if m3:
        items = re.findall(r"['\"]([^'\"]+)['\"]", m3.group(1))
        return items
    return []

def parse_setup_py(path: str) -> Set[str]:
    text = open(path, 'r', encoding='utf-8').read()
    m = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, flags=re.S)
    if m:
        inner = m.group(1)
        items = re.findall(r"['\"]([^'\"]+)['\"]", inner)
        return items
    m2 = re.search(r"requirements\s*=\s*\[(.*?)\]", text, flags=re.S)
    if m2:
        inner = m2.group(1)
        items = re.findall(r"['\"]([^'\"]+)['\"]", inner)
        return items
    return []

def normalize_dep_name(dep: str) -> str:
    dep = dep.strip().strip('"').strip("'")
    dep = dep.split("[")[0] 
    dep = re.split(r'[<>=!~]', dep)[0]
    return dep.strip()

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dependency graph visualizer (minimal prototype - stage 1)")
    p.add_argument('-p', '--package-name', required=True, type=validate_package_name,
                   help='Name of the package to analyze (required)')
    p.add_argument('-r', '--repo', required=True, type=validate_repo,
                   help='Repository URL or path to test repository (required)')
    p.add_argument('-m', '--repo-mode', default='auto', type=validate_repo_mode,
                   help=f"Mode of working with test repo. One of: {', '.join(sorted(REPO_MODES))}. Default: auto")
    p.add_argument('-v', '--version', default='latest', type=validate_version,
                   help="Package version to analyze (semver or 'latest'). Default: latest")
    p.add_argument('-o', '--output', default='dep_graph.png', type=validate_output,
                   help="Generated image filename (.png, .svg). Default: dep_graph.png")
    p.add_argument('-f', '--filter', default='', type=validate_filter,
                   help='Substring to filter packages by name (optional)')
    p.add_argument('--verbose', action='store_true', help='Verbose mode (prints extra diagnostics)')
    return p

def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except argparse.ArgumentError as ae:
        error(str(ae))
    except SystemExit as se:
        raise

    print("Received parameters:")
    for k, v in sorted(vars(args).items()):
        print(f"{k}: {v}")

    if args.repo_mode == 'local' and not os.path.isdir(args.repo):
        error(f"repo-mode 'local' requires that --repo points to a directory: {args.repo}")
    if args.repo_mode in ('git', 'http'):
        parsed = urlparse(args.repo)
        if parsed.scheme not in ('http', 'https', 'git', 'ssh'):
            error(f"repo-mode '{args.repo_mode}' requires a URL --repo (got: {args.repo})")

    if args.verbose:
        print('\n[DEBUG] Parameters validated successfully. Ready to analyze (not implemented in stage 1).')
    else:
        print('\nParameters validated successfully.')
    return 0

if __name__ == '__main__':
    try:
        rc = main()
        sys.exit(rc)
    except Exception as exc:
        error(str(exc))
