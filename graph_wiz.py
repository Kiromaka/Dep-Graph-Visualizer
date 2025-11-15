from __future__ import annotations
import argparse
import os
import re
import sys
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
