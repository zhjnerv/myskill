"""起草报告的窄范围 I/O 防护：输入别名隔离、输出互斥和原子替换。"""
from __future__ import annotations

import hashlib
import os
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Iterable


class DraftingOutputError(ValueError):
    """输出路径不安全；调用方应按输入/路径错误退出，不写失败报告。"""


def paths_alias(first: Path, second: Path) -> bool:
    if os.path.normcase(str(first.resolve())) == os.path.normcase(str(second.resolve())):
        return True
    try:
        return first.samefile(second)
    except FileNotFoundError:
        # 尚未生成的报告只能按规范化路径比较；其他文件系统错误不可静默忽略。
        return False


class DraftingOutputGuard:
    def __init__(self, inputs: Iterable[Path], outputs: Iterable[Path]) -> None:
        self.outputs = tuple(outputs)
        self._targets = tuple(path.resolve() for path in self.outputs)
        self._inputs: list[Path] = []
        self._source_snapshots: dict[Path, tuple[Path, str]] = {}
        self.protect_inputs(inputs)

    def protect_inputs(self, paths: Iterable[Path]) -> None:
        """保留输入原路径和首次解析目标，避免输入符号链接改向后遗忘原文。"""
        for path in paths:
            for protected in (path, path.resolve()):
                if protected not in self._inputs:
                    self._inputs.append(protected)
                if protected.is_file():
                    resolved = protected.resolve()
                    self._source_snapshots.setdefault(
                        protected, (resolved, hashlib.sha256(resolved.read_bytes()).hexdigest())
                    )
        self.check()

    def check(self) -> None:
        for source, (resolved, digest) in self._source_snapshots.items():
            if source.resolve() != resolved or hashlib.sha256(resolved.read_bytes()).hexdigest() != digest:
                raise DraftingOutputError(f"输入文件在校验期间发生变化：{source}")
        for output, target in zip(self.outputs, self._targets):
            if output.resolve() != target:
                raise DraftingOutputError(f"输出路径指向发生变化：{output}")
            for source in self._inputs:
                if paths_alias(output, source):
                    raise DraftingOutputError(f"输出路径不得与输入文件相同或互为别名：{output} / {source}")
        for first, second in combinations(self.outputs, 2):
            if paths_alias(first, second):
                raise DraftingOutputError(f"输出路径之间不得相同或互为别名：{first} / {second}")

    def write_texts(self, texts: Iterable[str]) -> None:
        """先暂存全部输出，再逐文件复检并替换；不承诺多个文件的事务回滚。"""
        payloads = tuple(texts)
        if len(payloads) != len(self.outputs):
            raise ValueError("输出正文数量与受保护路径数量不一致")
        self.check()
        staged: list[tuple[Path, Path]] = []
        try:
            for output, text in zip(self.outputs, payloads):
                output.parent.mkdir(parents=True, exist_ok=True)
                self.check()
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False,
                ) as handle:
                    # 固定临时文件的实际路径，避免父目录符号链接改向后清理错文件。
                    temporary = Path(handle.name).resolve()
                    staged.append((temporary, output))
                    handle.write(text.encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
            for temporary, output in staged:
                # 不能只在解析参数时检查：暂存期间路径可能被改成输入/其他输出的别名。
                self.check()
                os.replace(temporary, output)
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
