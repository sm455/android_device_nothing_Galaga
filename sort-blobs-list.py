#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

import ast
import re
from argparse import ArgumentParser
from functools import cmp_to_key
from itertools import groupby
from locale import LC_ALL, setlocale, strcoll
from pathlib import Path


def is_blob(line: str) -> bool:
    line = line.strip()
    return bool(line) and not line.startswith('#')


def get_source_file_name(line: str) -> str:
    # - Remove '-' from strings if there, it is used to indicate a build target
    # - Discard anything after:
    #   - ':' (destination path)
    #   - ';' (additional options)
    #   - '|' (sha1sum hash)
    regex_match = re.match(r'^-?(.+?)(?:[:;\\|].*?)?$', line)

    if not regex_match:
        return line

    return regex_match.group(1)


def strcoll_extract_utils(
    string1: str, string2: str, dir_first: bool = False
) -> int:
    if not string1 or not string2:
        return strcoll(string1, string2)

    string1 = get_source_file_name(string1)
    string2 = get_source_file_name(string2)

    if dir_first:
        if '/' not in string1 and '/' not in string2:
            return strcoll(string1, string2)

        string1_dir = string1.rsplit('/', 1)[0] + '/'
        string2_dir = string2.rsplit('/', 1)[0] + '/'

        if string1_dir == string2_dir:
            return strcoll(string1, string2)

        if string1_dir.startswith(string2_dir):
            return -1

        if string2_dir.startswith(string1_dir):
            return 1

    return strcoll(string1, string2)


def sort_proprietary_file(path: Path, sort_key) -> None:
    with path.open('r', encoding='utf-8') as f:
        sections = groupby(f.readlines(), is_blob)

    ordered_sections = []

    for sort, section in sections:
        if sort:
            ordered_sections.append(
                ''.join(sorted(section, key=sort_key))
            )
        else:
            ordered_sections.append(''.join(section))

    with path.open('w', encoding='utf-8') as f:
        f.write(''.join(ordered_sections))


def get_blob_paths(key: ast.expr) -> list[str]:
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return [key.value]

    if isinstance(key, (ast.Tuple, ast.List)):
        paths = []

        for item in key.elts:
            if not isinstance(item, ast.Constant) or not isinstance(
                item.value, str
            ):
                raise ValueError(
                    'blob_fixups keys must contain string paths'
                )

            paths.append(item.value)

        return paths

    raise ValueError(
        'Unsupported key in blob_fixups; expected string paths'
    )


def format_blob_key(paths: list[str], indent: str = '    ') -> str:
    # Single blob:
    #
    #     'vendor/bin/mnld': blob_fixup()
    #
    if len(paths) == 1:
        return f"{indent}{paths[0]!r}"

    # Multiple blobs:
    #
    #     (
    #         'vendor/lib64/foo.so',
    #         'vendor/lib64/bar.so',
    #     )
    #
    lines = [f'{indent}(']
    lines.extend(
        f"{indent}    {path!r},"
        for path in paths
    )
    lines.append(f'{indent})')

    return '\n'.join(lines)


def sort_blob_fixups(
    path: Path,
    sort_key,
    dir_first: bool = False,
) -> None:
    source = path.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(path))

    blob_dict = None

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == 'blob_fixups'
            ):
                blob_dict = node.value
                break

        elif isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name)
                and target.id == 'blob_fixups'
                for target in node.targets
            ):
                blob_dict = node.value
                break

    if not isinstance(blob_dict, ast.Dict):
        raise ValueError(
            f'No blob_fixups dictionary found in {path}'
        )

    lines = source.splitlines(keepends=True)
    entries = []

    for key_node, value_node in zip(
        blob_dict.keys,
        blob_dict.values,
    ):
        if key_node is None:
            continue

        paths = get_blob_paths(key_node)

        # Sort blobs inside each fixup,
        # but never split a fixup group.
        paths = sorted(paths, key=sort_key)

        value_text = ast.get_source_segment(
            source,
            value_node,
        )

        if value_text is None:
            raise ValueError(
                f'Could not read blob_fixup value in {path}'
            )

        value_text = value_text.rstrip().removesuffix(',')

        # Normalize the complete blob_fixup expression first.
        # This handles both normal multi-line fixups and malformed
        # expressions where multiple chained calls were placed on
        # the same physical line.
        value_text = ' '.join(
            line.strip()
            for line in value_text.splitlines()
            if line.strip()
        )

        if not value_text:
            raise ValueError(
                f'Empty blob_fixup value in {path}'
            )

        key_text = format_blob_key(paths)

        # Find every chained .method( call.  Each call is emitted
        # on its own line with exactly 8 spaces of indentation.
        call_matches = list(
            re.finditer(
                r'\.[A-Za-z_]\w*\s*\(',
                value_text,
            )
        )

        if not call_matches:
            entry_text = (
                key_text
                + ': '
                + value_text
                + ','
            )
        else:
            first_call = call_matches[0]
            base_text = value_text[:first_call.start()].strip()

            entry_text = (
                key_text
                + ': '
                + base_text
            )

            for index, match in enumerate(call_matches):
                call_start = match.start()

                if index + 1 < len(call_matches):
                    call_end = call_matches[index + 1].start()
                else:
                    call_end = len(value_text)

                call = value_text[call_start:call_end].strip()

                if call:
                    entry_text += (
                        '\n'
                        + '        '
                        + call
                    )

            entry_text += ','

        entries.append(
            (
                paths[0],
                entry_text,
            )
        )

    entries.sort(
        key=cmp_to_key(
            lambda a, b: strcoll_extract_utils(
                a[0],
                b[0],
                dir_first,
            )
        )
    )

    # Find the dictionary's opening and closing braces
    # using AST positions.
    dict_start = (
        blob_dict.lineno - 1,
        blob_dict.col_offset,
    )

    dict_end = (
        blob_dict.end_lineno - 1,
        blob_dict.end_col_offset,
    )

    start_offset = (
        sum(
            len(line)
            for line in lines[:dict_start[0]]
        )
        + dict_start[1]
    )

    end_offset = (
        sum(
            len(line)
            for line in lines[:dict_end[0]]
        )
        + dict_end[1]
    )

    dict_source = source[
        start_offset:end_offset
    ]

    open_brace = dict_source.find('{')
    close_brace = dict_source.rfind('}')

    if open_brace < 0 or close_brace < 0:
        raise ValueError(
            f'Could not locate blob_fixups braces in {path}'
        )

    replacement = (
        dict_source[:open_brace + 1]
        + '\n'
        + '\n'.join(
            entry_text
            for _, entry_text in entries
        )
        + '\n}'
    )

    # Keep any source after the dictionary's closing brace.
    new_source = (
        source[:start_offset]
        + replacement
        + source[end_offset:]
    )

    path.write_text(
        new_source,
        encoding='utf-8',
    )


if __name__ == '__main__':
    setlocale(LC_ALL, 'C')

    parser = ArgumentParser(
        description=(
            'Sort proprietary blobs or '
            'extract.py blob_fixups'
        )
    )

    parser.add_argument(
        'files',
        nargs='*',
        help=(
            'Files to sort '
            '(use *.txt or *.py)'
        ),
    )

    args = parser.parse_args()

    # With no arguments, sort both files in the current directory.
    if not args.files:
        args.files = ['proprietary-files.txt', 'extract-files.py']

        # Make extract-files.py executable by default.
        extract_script = Path('extract-files.py')
        if extract_script.is_file():
            extract_script.chmod(extract_script.stat().st_mode | 0o111)

    # Directory-first sorting is always enabled.
    sort_key = cmp_to_key(
        lambda x, y: strcoll_extract_utils(
            x,
            y,
            True,
        )
    )

    for file in args.files:
        path = Path(file)

        if not path.is_file():
            print(f'File {file} not found')
            continue

        try:
            if path.suffix == '.py':
                sort_blob_fixups(
                    path,
                    sort_key,
                    True,
                )
            else:
                sort_proprietary_file(
                    path,
                    sort_key,
                )

        except (
            SyntaxError,
            ValueError,
        ) as error:
            print(
                f'Could not sort {file}: {error}'
            )
