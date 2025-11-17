from __future__ import annotations
import argparse
import configparser
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from typing import List, Set, Dict, Tuple
from urllib.parse import urlparse

SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-.]+)?(?:\+[0-9A-Za-z-.]+)?$"
)
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_OUTPUT_EXTS = {".png", ".svg", ".svgz"}
REPO_MODES = {"auto", "local", "git", "http"}


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
    if value.startswith("git@") or re.match(r"^[\w.+-]+@[\w.-]+:", value):
        return value
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https", "git", "ssh"):
        if not parsed.netloc:
            raise argparse.ArgumentTypeError(f"repo URL looks invalid: {value}")
        return value
    if os.path.exists(value):
        return os.path.abspath(value)
    raise argparse.ArgumentTypeError(f"repo path does not exist: {value}")


def validate_repo_mode(value: str) -> str:
    v = value.lower()
    if v not in REPO_MODES:
        raise argparse.ArgumentTypeError(
            f"repo-mode must be one of: {', '.join(sorted(REPO_MODES))}"
        )
    return v


def validate_version(value: str) -> str:
    if value == "latest":
        return value
    if SEMVER_RE.match(value):
        return value
    raise argparse.ArgumentTypeError(
        "version must be 'latest' or follow semantic versioning (e.g. 1.2.3)"
    )


def validate_output(value: str) -> str:
    root, ext = os.path.splitext(value)
    if ext == "":
        raise argparse.ArgumentTypeError(
            "output file must have an extension like .png or .svg"
        )
    if ext.lower() not in VALID_OUTPUT_EXTS:
        raise argparse.ArgumentTypeError(
            f"unsupported output extension '{ext}'; supported: {', '.join(sorted(VALID_OUTPUT_EXTS))}"
        )
    dirpath = os.path.dirname(value) or "."
    if not os.path.isdir(dirpath):
        raise argparse.ArgumentTypeError(f"output directory does not exist: {dirpath}")
    test_path = os.path.join(dirpath, f".depviz_tmp_write_test_{os.getpid()}")
    try:
        with open(test_path, "w") as f:
            f.write("x")
        os.remove(test_path)
    except Exception as e:
        raise argparse.ArgumentTypeError(f"no write permission in output directory '{dirpath}': {e}")
    return os.path.abspath(value)


def validate_filter(value: str) -> str:
    if value is None:
        return ""
    return value


def has_git() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def clone_repo(repo: str, dest: str, version: str | None = None) -> None:
    if not has_git():
        raise RuntimeError("Git is not installed or not found in PATH; cannot clone repository")
    cmd = ["git", "clone", "--depth", "1", repo, dest]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to clone repository '{repo}': {e}")
    if version and version != "latest":
        try:
            subprocess.run(["git", "checkout", version], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError:
            try:
                subprocess.run(["git", "fetch", "--tags"], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                subprocess.run(["git", "checkout", version], cwd=dest, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to checkout version '{version}' in repository '{repo}': {e}")


def is_remote_repo_like(repo: str) -> bool:
    if repo.startswith("git@") or re.match(r"^[\w.+-]+@[\w.-]+:", repo):
        return True
    parsed = urlparse(repo)
    return parsed.scheme in ("http", "https", "git", "ssh")


def prepare_repo(repo: str, repo_mode: str, version: str) -> str:
    tmpdir = tempfile.mkdtemp(prefix="depviz_repo_")
    try:
        if is_remote_repo_like(repo):
            clone_repo(repo, tmpdir, version)
            return tmpdir
        else:
            abs_path = os.path.abspath(repo)
            if not os.path.isdir(abs_path):
                raise RuntimeError(f"Local repository path is not a directory: {abs_path}")
            shutil.copytree(abs_path, tmpdir, dirs_exist_ok=True)
            git_dir = os.path.join(tmpdir, ".git")
            if os.path.isdir(git_dir) and version and version != "latest":
                try:
                    subprocess.run(["git", "checkout", version], cwd=tmpdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                except subprocess.CalledProcessError:
                    pass
            return tmpdir
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def parse_requirements_file(req_file_path: str) -> Set[str]:
    dependencies: Set[str] = set()
    if not os.path.isfile(req_file_path):
        return dependencies
    with open(req_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg_name = re.split(r"[<>=!~]", line)[0].strip()
            if pkg_name:
                dependencies.add(pkg_name)
    return dependencies


def parse_setup_cfg(path: str) -> Set[str]:
    deps: Set[str] = set()
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    if cfg.has_section("options") and cfg.has_option("options", "install_requires"):
        raw = cfg.get("options", "install_requires")
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pkg = re.split(r"[<>=!~]", line)[0].strip()
            if pkg:
                deps.add(pkg)
    return deps


def parse_pyproject_toml(path: str) -> Set[str]:
    text = open(path, "r", encoding="utf-8").read()
    m = re.search(r"(?ms)^\s*\[project\].*?^dependencies\s*=\s*\[(.*?)\]", text)
    if m:
        inner = m.group(1)
        items = re.findall(r"['\"]([^'\"]+)['\"]", inner)
        return set(items)
    m2 = re.search(r"(?ms)^\s*\[tool\.poetry\].*?^dependencies\s*=\s*\{(.*?)\}", text)
    if m2:
        block = m2.group(1)
        deps = []
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("=", 1)
            pkg_name = parts[0].strip().strip('"').strip("'")
            if pkg_name.lower() != "python":
                deps.append(pkg_name)
        return set(deps)
    m3 = re.search(r"(?ms)^\s*\[tool\.flit\.metadata\].*?^requires\s*=\s*\[(.*?)\]", text)
    if m3:
        items = re.findall(r"['\"]([^'\"]+)['\"]", m3.group(1))
        return set(items)
    return set()


def parse_setup_py(path: str) -> Set[str]:
    text = open(path, "r", encoding="utf-8").read()
    m = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, flags=re.S)
    if m:
        inner = m.group(1)
        items = re.findall(r"['\"]([^'\"]+)['\"]", inner)
        return set(items)
    m2 = re.search(r"requirements\s*=\s*\[(.*?)\]", text, flags=re.S)
    if m2:
        inner = m2.group(1)
        items = re.findall(r"['\"]([^'\"]+)['\"]", inner)
        return set(items)
    return set()


def normalize_dep_name(dep: str) -> str:
    dep = dep.strip().strip('"').strip("'")
    dep = dep.split("[")[0]
    dep = re.split(r"[<>=!~]", dep)[0]
    return dep.strip()


def collect_direct_dependencies(repo_path: str) -> Set[str]:
    candidates = [
        os.path.join(repo_path, "pyproject.toml"),
        os.path.join(repo_path, "setup.cfg"),
        os.path.join(repo_path, "setup.py"),
        os.path.join(repo_path, "requirements.txt"),
    ]
    deps: List[str] = []
    found_any = False
    if os.path.isfile(candidates[0]):
        found_any = True
        deps.extend(parse_pyproject_toml(candidates[0]))
    if os.path.isfile(candidates[1]):
        found_any = True
        deps.extend(parse_setup_cfg(candidates[1]))
    if os.path.isfile(candidates[2]):
        found_any = True
        deps.extend(parse_setup_py(candidates[2]))
    if os.path.isfile(candidates[3]):
        found_any = True
        deps.extend(parse_requirements_file(candidates[3]))
    if not found_any:
        for root, dirs, files in os.walk(repo_path):
            for fname in files:
                fname_l = fname.lower()
                file_path = os.path.join(root, fname)
                if fname_l == "requirements.txt":
                    deps.extend(parse_requirements_file(file_path))
                elif fname_l == "setup.cfg":
                    deps.extend(parse_setup_cfg(file_path))
                elif fname_l == "setup.py":
                    deps.extend(parse_setup_py(file_path))
                elif fname_l == "pyproject.toml":
                    deps.extend(parse_pyproject_toml(file_path))
    normalized_deps = {normalize_dep_name(d) for d in deps if normalize_dep_name(d)}
    normalized_deps.discard("")
    return normalized_deps

def load_test_graph(path: str) -> Dict[str, Set[str]]:
    if not os.path.isfile(path):
        raise RuntimeError(f"Test graph file does not exist: {path}")
    graph: Dict[str, Set[str]] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ':' in line:
                left, right = line.split(":", 1)
                node = left.strip()
                deps = [p.strip() for p in re.split(r"[,\s]+", right.strip()) if p.strip()]
                graph[node] = set(deps)
            elif "->" in line:
                left, right = line.split("->", 1)
                node = left.strip()
                deps = [p.strip() for p in re.split(r"[,\s]+", right.strip()) if p.strip()]
                graph[node] = set(deps)
            else:
                node = line.strip()
                graph[node] = set()
    return graph

def build_graph_from_test(start: str, graph: Dict[str, Set[str]], ignore_substr: str) -> Tuple[Set[str], Set[Tuple[str, str]], List[List[str]]]:
    visited: Set[str] = set()
    onstack: Set[str] = set()
    edges: Set[Tuple[str, str]] = set()
    cycles: List[List[str]] = []
    path_stack: List[str] = []

    def dfs(u: str):
        if ignore_substr and ignore_substr in u:
            return
        if u in path_stack:  # если уже в текущем пути — цикл
            idx = path_stack.index(u)
            cycles.append(path_stack[idx:] + [u])
            return
        if u in visited:
            return
        visited.add(u)
        path_stack.append(u)
        for v in sorted(graph.get(u, set())):
            if ignore_substr and ignore_substr in v:
                continue
            edges.add((u, v))
            dfs(v)
        path_stack.pop()
    dfs(start)
    return visited, edges, cycles

def build_graph_from_repo(start: str, direct_deps: Set[str], repo_path: str, ignore_substr: str) -> Tuple[Set[str], Set[Tuple[str, str]], List[List[str]]]:
    graph: Dict[str, Set[str]] = {start: set(d for d in direct_deps if not (ignore_substr and ignore_substr in d))}
    visited: Set[str] = set()
    onstack: Set[str] = set()
    edges: Set[Tuple[str, str]] = set()
    cycles: List[List[str]] = []
    path_stack: List[str] = []

    def dfs(u: str):
        if ignore_substr and ignore_substr in u:
            return
        if u in path_stack:  # если уже в текущем пути — цикл
            idx = path_stack.index(u)
            cycles.append(path_stack[idx:] + [u])
            return
        if u in visited:
            return
        visited.add(u)
        path_stack.append(u)
        for v in sorted(graph.get(u, set())):
            if ignore_substr and ignore_substr in v:
                continue
            edges.add((u, v))
            dfs(v)
        path_stack.pop()

    dfs(start)
    return visited, edges, cycles

def print_graph_result(start: str, nodes: Set[str], edges: Set[Tuple[str, str]], cycles: List[List[str]], ignore_substr: str):
    print(f"Dependency graph starting from '{start}':")
    if ignore_substr:
        print(f"(ignoring packages containing substring '{ignore_substr}')")
    print(f"Total nodes: {len(nodes)}")
    for node in sorted(nodes):
        print(f" - {node}")
    print(f"Total edges: {len(edges)}")
    for src, dst in sorted(edges):
        print(f" {src} -> {dst}")
    if cycles:
        print(f"Detected {len(cycles)} cycles:")
        for cycle in cycles:
            print(" -> ".join(cycle))
    else:
        print("No cycles detected.")

def find_reverse_dependencies(target: str, edges: Set[Tuple[str, str]], extra_nodes: Set[str] | None = None) -> Set[str]:
    reverse_graph: Dict[str, Set[str]] = {}
    for a, b in edges:
        reverse_graph.setdefault(b, set()).add(a)
        reverse_graph.setdefault(a, set())
    if extra_nodes:
        for n in extra_nodes:
            reverse_graph.setdefault(n, set())
    visited: Set[str] = set()
    def dfs(u: str):
        for v in sorted(reverse_graph.get(u, set())):
            if v in visited:
                continue
            visited.add(v)
            dfs(v)
    dfs(target)
    visited.discard(target)
    return visited

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dependency graph visualizer (stage 3)")
    p.add_argument("-p", "--package-name", required=True, type=validate_package_name, help="Name of the package to analyze (required)")
    p.add_argument("-r", "--repo", required=False, type=validate_repo, help="Repository URL or path to test repository (optional when --test-file is used)")
    p.add_argument("--test-file", required=False, type=str, help="Path to test graph file (optional)")
    p.add_argument("-m", "--repo-mode", default="auto", type=validate_repo_mode, help=f"Mode of working with test repo. One of: {', '.join(sorted(REPO_MODES))}. Default: auto")
    p.add_argument("-v", "--version", default="latest", type=validate_version, help="Package version to analyze (semver or 'latest'). Default: latest")
    p.add_argument("-o", "--output", default="dep_graph.png", type=validate_output, help="Generated image filename (.png, .svg). Default: dep_graph.png")
    p.add_argument("-f", "--filter", default="", type=validate_filter, help="Substring to filter packages by name (optional)")
    p.add_argument("--reverse", dest="reverse_target", required=False, type = str, help = "Show reverse dependencies for the specified package")
    p.add_argument("--verbose", action="store_true", help="Verbose mode (prints extra diagnostics)")
    return p


def generate_dot(nodes: Set[str], edges: Set[Tuple[str, str]], start: str) -> str:
    lines = []
    lines.append("digraph G {")
    lines.append('  node [shape=box, style=filled, color=lightgrey];')
    if start in nodes:
        lines.append(f'  "{start}" [color=lightblue, style=filled];')
    for n in sorted(nodes):
        if n == start:
            continue
        lines.append(f'  "{n}";')
    for src, dst in sorted(edges):
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)

def render_svg(dot_text: str, svg_path: str) -> None:
    base = os.path.splitext(svg_path)[0]
    dot_path = base + ".tmp.dot"
    out_dir = os.path.dirname(os.path.abspath(dot_path)) or "."

    os.makedirs(out_dir, exist_ok=True)

    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out_dir, delete=False, suffix=".dot", prefix="tmp_") as tf:
            tf.write(dot_text)
            tf.flush()
            temp_name = tf.name

        try:
            os.replace(temp_name, dot_path)
        except Exception:
            try:
                os.remove(dot_path)
            except Exception:
                pass
            os.replace(temp_name, dot_path)

        try:
            subprocess.run(["dot", "-Tsvg", dot_path, "-o", svg_path], check=True)
            try:
                os.remove(dot_path)
            except Exception:
                pass
            print(f"SVG graph generated at: {svg_path}")
        except FileNotFoundError:
            print(f"Graphviz 'dot' not found, try downloading at https://graphviz.org/download/; DOT file saved at: {dot_path}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to render SVG with dot: {e}", file=sys.stderr)
            print(f"DOT file is available at: {dot_path}")
    except Exception as e:
        print(f"Failed to write DOT file: {e}", file=sys.stderr)




def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    print("Received parameters:")
    for k, v in sorted(vars(args).items()):
        print(f"{k}: {v}")
    if not args.test_file and not args.repo:
        error("Either --repo or --test-file must be specified")
    repo_path = None
    if args.test_file:
        try:
            test_graph = load_test_graph(args.test_file)
        except Exception as e:
            error(f"Failed to load test graph: {e}")
        start = args.package_name
        edges_all: Set[Tuple[str, str]] = set()
        nodes_all: Set[str] = set()
        for u, vs in test_graph.items():
            if args.filter and args.filter in u:
                continue
            nodes_all.add(u)
            for v in vs:
                if args.filter and args.filter in v:
                    continue
                nodes_all.add(v)
                edges_all.add((u, v))
        nodes, edges, cycles = build_graph_from_test(start, test_graph, args.filter)
    print_graph_result(start, nodes, edges, cycles, args.filter)

    svg_path = os.path.splitext(args.output)[0] + ".svg"
    dot_text = generate_dot(nodes, edges, start)
    render_svg(dot_text, svg_path)

    if args.reverse_target:
        source_edges = edges_all if args.test_file else edges
        reverse_set = find_reverse_dependencies(args.reverse_target, source_edges, extra_nodes=(nodes_all if args.test_file else None))
        print()
        print(f"Packages depending on '{args.reverse_target}':")
        if reverse_set:
            for n in sorted(reverse_set):
                print(f" - {n}")
        else:
            print(" None")
    if repo_path:
        try:
            shutil.rmtree(repo_path, ignore_errors=True)
        except Exception:
            pass
    return 0



if __name__ == "__main__":
    try:
        rc = main()
        sys.exit(rc)
    except Exception as e:
        error(str(e))
