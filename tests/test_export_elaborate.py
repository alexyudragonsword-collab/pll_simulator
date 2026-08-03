"""Cross-reference checks on the generated Verilog-AMS / RNM.

No free simulator elaborates Verilog-AMS, so this export has never been
compiled by anything -- the existing structure tests check that files exist
and that begin/end nest, which a top instantiating a module that was renamed
would still pass.  These do the part of elaboration that is a text problem:
every instantiated module exists, every named port on an instance is a port
the module actually declares, and no instance leaves a declared input
unconnected.

That is not the same as "it elaborates", and it is not claimed to be.  It is
the class of error that renaming a port actually produces, caught without a
licence.
"""
import re
from collections import defaultdict

import pytest

from pllsim import presets
from pllsim.export import export

# `module foo (...);` through the matching `endmodule`
_MODULE = re.compile(r"\bmodule\s+(\w+)\s*(#\s*\(.*?\))?\s*\((.*?)\)\s*;(.*?)\bendmodule",
                     re.S)
# `foo #(...) inst (.a(x), .b(y));`  or  `foo inst (.a(x));`.  The parameter
# override routinely wraps across lines, so \s* after it -- matching only
# [ \t] there found zero instantiations in the AMS tops, which is how a
# whole family of these checks came to pass vacuously.
_INSTANCE = re.compile(
    r"^[ \t]*(\w+)[ \t]*(#\s*\([^;]*?\))?\s*(\w+)\s*\(([^;]*?)\)\s*;",
    re.S | re.M)
_NAMED_PORT = re.compile(r"\.(\w+)\s*\(")
# Two declaration styles have to work.  Non-ANSI bodies say `input up, dn;`
# -- one keyword, several names, so taking only the first reports every other
# port as undeclared.  ANSI headers say `input ref_clk, output dbg_dt, ...)`
# with a single terminating `;` -- so scanning to the next `;` puts every port
# under the first direction and calls the debug outputs inputs.  Scanning
# keyword-to-keyword handles both.
_DIRECTION = re.compile(r"\b(input|output|inout)\b")
_RANGE = re.compile(r"\[[^\]]*\]")
_TYPE_WORDS = {"wire", "reg", "real", "wreal", "electrical", "signed",
               "integer", "logic"}

_KEYWORDS = {"module", "endmodule", "if", "else", "for", "while", "case",
             "begin", "end", "always", "initial", "assign", "function",
             "task", "analog", "real", "wire", "reg", "integer", "parameter",
             "localparam", "input", "output", "inout", "wreal", "electrical",
             "generate", "endgenerate", "repeat", "forever", "return",
             "$fopen", "$fclose", "$display", "$finish", "$fwrite"}


def _port_names(text: str) -> dict[str, str]:
    """{port: direction}, handling both ANSI headers and non-ANSI bodies."""
    hits = list(_DIRECTION.finditer(text))
    out = {}
    for i, m in enumerate(hits):
        stop = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        seg = text[m.end():stop]
        seg = seg.split(";")[0]                   # a `;` ends the declaration
        for chunk in _RANGE.sub(" ", seg).split(","):
            words = [w for w in re.findall(r"\w+", chunk)
                     if w not in _TYPE_WORDS and not w.isdigit()]
            if words:
                out[words[-1]] = m.group(1)
    return out


def _modules(text: str) -> dict[str, list[str]]:
    """{module_name: [declared port names]} for every module in a file."""
    out = {}
    for m in _MODULE.finditer(text):
        name, _, header, body = m.groups()
        ports = _port_names(header + ";")
        if not ports:      # ANSI-less header: directions are inside the body
            ports = _port_names(body)
        out[name] = ports
    return out


def _instances(body: str, known: set[str] | None = None):
    """(module, instance, [named ports]) for every instantiation in a body.

    `known` restricts to modules in the library.  Leave it None to see
    instantiations of modules that are NOT defined -- which is the whole point
    of the missing-module check, and impossible if the filter is unconditional.
    """
    for m in _INSTANCE.finditer(body):
        mod, _, inst, args = m.groups()
        if mod in _KEYWORDS or inst in _KEYWORDS:
            continue
        if not _NAMED_PORT.search(args):
            continue                      # positional or not an instantiation
        if known is not None and mod not in known:
            continue
        yield mod, inst, _NAMED_PORT.findall(args)


@pytest.fixture(scope="module")
def libraries(tmp_path_factory):
    """One export per preset, parsed into a module table.

    rnm/ and ams/ are merged into a single library because that is how they
    are compiled: the mostly-digital architectures' electrical top wraps the
    RNM core as u_core, so splitting the directories makes a module that is
    right there look missing.
    """
    out = tmp_path_factory.mktemp("elab")
    libs = {}
    for nm, mk in presets.ALL_PRESETS.items():
        rep = export(mk(), out, name=nm, n_golden=256, n_vectors=128)
        table, bodies = {}, {}
        for sub in ("rnm", "ams"):
            d = rep.outdir / sub
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.vams")) + sorted(d.glob("*.v")):
                txt = p.read_text()
                table.update(_modules(txt))
                for m in _MODULE.finditer(txt):
                    bodies[m.group(1)] = m.group(4)
        libs[nm] = (table, bodies)
    return libs


def test_every_export_defines_modules(libraries):
    assert libraries, "nothing was exported"
    for key, (table, _) in libraries.items():
        assert table, f"{key}: no modules parsed"


def test_the_parser_actually_finds_instantiations(libraries):
    """Guard against passing vacuously.

    Every check below is 'no bad instance found'.  If the regex stopped
    matching, they would all pass while checking nothing -- so count what was
    seen and require a hierarchy to exist.
    """
    total = 0
    for name, (table, bodies) in libraries.items():
        seen = sum(len(list(_instances(b, set(table)))) for b in bodies.values())
        # smallest real hierarchy: two testbenches, plus an electrical top
        # that either instantiates analog blocks or wraps the RNM core
        assert seen >= 2, f"{name}: parsed only {seen} instantiations"
        total += seen
    # tied to the export count rather than a magic number, so adding a preset
    # cannot quietly lower the bar
    assert total >= 2 * len(libraries), \
        f"only {total} instantiations across {len(libraries)} exports"


def test_a_renamed_port_is_caught():
    """Prove the port check has teeth, on a library with a known defect."""
    lib = {"mutant": (
        {"child": {"clk": "input", "d": "input", "q": "output"},
         "parent": {"clk": "input"}},
        {"parent": "  child u0 (.clk(clk), .dd(x), .q(y));\n", "child": ""})}
    with pytest.raises(AssertionError, match=r"\.dd"):
        test_every_named_port_is_declared_on_the_module(lib)


def test_a_missing_module_is_caught():
    """A module that was renamed leaves an instantiation pointing at nothing."""
    lib = {"mutant": (
        {"parent": {"clk": "input"}},
        {"parent": "  ghost u0 (.clk(clk));\n"})}
    with pytest.raises(AssertionError, match="never defined"):
        test_every_instantiated_module_exists(lib)


def test_every_instantiated_module_exists(libraries):
    missing = defaultdict(list)
    for name, (table, bodies) in libraries.items():
        for parent, body in bodies.items():
            for mod, inst, _ in _instances(body):      # unfiltered on purpose
                if mod not in table:
                    missing[name].append(f"{parent} -> {mod} ({inst})")
    assert not missing, f"instantiated but never defined: {dict(missing)}"


def test_the_rnm_top_is_flat_and_the_ams_top_is_not(libraries):
    """Pin the two exports' shapes, because they differ deliberately.

    The RNM top is a flat transplant of the golden engine so its output is
    bit-comparable against golden_rnm.csv -- the block library beside it is
    there to build from, not because the top uses it.  The electrical AMS top
    IS hierarchical, and a flat one would mean the electrical claim is empty.
    """
    for name, (table, bodies) in libraries.items():
        rnm = next(m for m in table if m.endswith("_top_rnm"))
        ams = next(m for m in table if m.endswith("_top_ams"))
        used_rnm = [m for m, _, _ in _instances(bodies[rnm], set(table))]
        used_ams = [m for m, _, _ in _instances(bodies[ams], set(table))]
        assert not used_rnm, f"{name}: the RNM top became hierarchical: {used_rnm}"
        # a sub-sampling loop has no charge pump, and the mostly-digital
        # architectures wrap the RNM core instead of an analog chain
        assert len(used_ams) >= 1, f"{name}: the electrical top went flat"


def test_every_named_port_is_declared_on_the_module(libraries):
    """A renamed port is the failure this catches: the instantiation still
    parses, still balances, and connects to nothing."""
    bad = defaultdict(list)
    for name, (table, bodies) in libraries.items():
        known = set(table)
        for parent, body in bodies.items():
            for mod, inst, ports in _instances(body, known):
                declared = set(table[mod])
                if not declared:
                    continue
                for p in ports:
                    if p not in declared:
                        bad[name].append(f"{parent}.{inst}({mod}): .{p}")
    assert not bad, f"connected to undeclared ports: {dict(bad)}"


def test_no_instance_leaves_an_input_unconnected(libraries):
    """Every INPUT of an instantiated module must appear in the connection
    list -- a floating input is a silent X in elaboration.

    Outputs are deliberately exempt: the electrical tops leave the RNM core's
    debug outputs dangling, which is both normal and correct.
    """
    bad = defaultdict(list)
    for name, (table, bodies) in libraries.items():
        known = set(table)
        for parent, body in bodies.items():
            for mod, inst, ports in _instances(body, known):
                declared = table[mod]
                if not declared or not ports:
                    continue
                floating = [p for p, d in declared.items()
                            if d == "input" and p not in set(ports)]
                if floating:
                    bad[name].append(f"{parent}.{inst}({mod}): {floating}")
    assert not bad, f"floating inputs: {dict(bad)}"


def test_module_names_are_unique_within_a_library(libraries):
    """Two definitions of the same name is a link-order coin flip."""
    for name, (table, bodies) in libraries.items():
        assert len(table) == len(bodies), \
            f"{name}: duplicate module definitions"


def test_no_module_instantiates_itself(libraries):
    for name, (table, bodies) in libraries.items():
        known = set(table)
        for parent, body in bodies.items():
            for mod, _, _ in _instances(body, known):
                assert mod != parent, f"{name}: {parent} instantiates itself"


def test_generated_reals_are_finite_literals(libraries):
    """A nan or inf in a parameter is accepted by the text and fatal at
    elaboration; the numbers come from a config, so this is reachable."""
    pat = re.compile(r"\b(nan|inf|-inf|1e\+?999)\b", re.I)
    for name, (_, bodies) in libraries.items():
        for parent, body in bodies.items():
            code = "\n".join(ln.split("//")[0] for ln in body.splitlines())
            hit = pat.search(code)
            assert hit is None, f"{name}/{parent}: {hit.group(0)!r}"
